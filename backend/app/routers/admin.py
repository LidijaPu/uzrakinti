"""Filialų ir kambarių administravimas. Kiekvienas pakeitimas sinchronizuojamas į ES ir invaliduoja Redis cache."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..cache import invalidate
from ..db import ROOMS_INDEX, db, es
from ..deps import require_role
from ..events import log_event
from ..services.search_sync import index_room, reindex_all_rooms
from ..utils import oid, serialize

router = APIRouter(tags=["admin"])
ADMIN = require_role("admin")
MANAGER = require_role("manager", "admin")

LT = str.maketrans("ąčęėįšųūž", "aceeisuuz")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().translate(LT)).strip("-")


class LocationIn(BaseModel):
    name: str
    city: str
    address: str
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class LocationPatch(BaseModel):
    name: str | None = None
    city: str | None = None
    address: str | None = None


class HintIn(BaseModel):
    order: int = Field(ge=1)
    text: str
    penaltySec: int = 120


class RoomIn(BaseModel):
    locationId: str
    name: str
    theme: str
    description: str = ""
    difficulty: int = Field(ge=1, le=5)
    minPlayers: int = Field(ge=1)
    maxPlayers: int = Field(le=12)
    durationMin: int = 60
    ageLimit: int = 10
    pricePerPlayer: float = Field(gt=0)
    tags: list[str] = []
    slotTimes: list[str] = ["10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00", "20:30"]
    hints: list[HintIn] = []


class RoomPatch(BaseModel):
    name: str | None = None
    theme: str | None = None
    description: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    minPlayers: int | None = None
    maxPlayers: int | None = Field(default=None, le=12)
    pricePerPlayer: float | None = Field(default=None, gt=0)
    tags: list[str] | None = None
    slotTimes: list[str] | None = None
    hints: list[HintIn] | None = None
    isActive: bool | None = None


def hints_doc(hints: list[HintIn]) -> list[dict]:
    return [{"hintId": f"h{h.order}", "order": h.order, "text": h.text, "penaltySec": h.penaltySec}
            for h in hints]


@router.get("/locations", summary="Filialų sąrašas su aktyvių kambarių skaičiumi")
def list_locations():
    rows = db.locations.aggregate([
        {"$lookup": {"from": "rooms", "localField": "_id", "foreignField": "locationId", "as": "rooms"}},
        {"$addFields": {"roomsCount": {"$size": {"$filter": {"input": "$rooms", "as": "x",
                                                             "cond": "$$x.isActive"}}}}},
        {"$project": {"rooms": 0}},
        {"$sort": {"city": 1, "name": 1}},
    ])
    return [serialize(x) for x in rows]


@router.post("/admin/locations", status_code=201, summary="Sukurti filialą")
def create_location(body: LocationIn, user: dict = Depends(ADMIN)):
    res = db.locations.insert_one({"name": body.name, "city": body.city, "address": body.address,
                                   "geo": {"type": "Point", "coordinates": [body.lng, body.lat]}})
    return {"id": str(res.inserted_id)}


@router.patch("/admin/locations/{location_id}", summary="Redaguoti filialą (persindeksuoja jo kambarius)")
def update_location(location_id: str, body: LocationPatch, user: dict = Depends(ADMIN)):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "Nėra ką keisti")
    loc = db.locations.find_one_and_update({"_id": oid(location_id)}, {"$set": changes},
                                           return_document=ReturnDocument.AFTER)
    if not loc:
        raise HTTPException(404, "Filialas nerastas")
    # ES dokumentuose filialo duomenys denormalizuoti → persindeksuojam jo kambarius
    rooms = list(db.rooms.find({"locationId": loc["_id"]}, {"slug": 1}))
    for room in rooms:
        index_room(room["_id"])
    invalidate(*[f"cache:room:{x['slug']}" for x in rooms])
    return serialize(loc)


@router.post("/admin/rooms", status_code=201, summary="Sukurti kambarį (+ ElasticSearch)")
def create_room(body: RoomIn, user: dict = Depends(MANAGER)):
    if body.minPlayers > body.maxPlayers:
        raise HTTPException(400, "minPlayers negali būti didesnis už maxPlayers")
    if not db.locations.find_one({"_id": oid(body.locationId)}, {"_id": 1}):
        raise HTTPException(404, "Filialas nerastas")
    doc = body.model_dump()
    doc.update({"locationId": oid(body.locationId), "slug": slugify(body.name), "isActive": True,
                "rating": {"avg": 0.0, "count": 0}, "hints": hints_doc(body.hints)})
    try:
        res = db.rooms.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Kambarys tokiu pavadinimu jau yra")
    index_room(res.inserted_id)
    es.indices.refresh(index=ROOMS_INDEX)  # kad paieška rastų iškart
    invalidate(f"cache:room:{doc['slug']}")  # jei kas nors anksčiau gavo „nerasta“ – išvalom
    log_event("room_created", user_id=user["userId"], room_id=str(res.inserted_id),
              location_id=body.locationId)
    return {"id": str(res.inserted_id), "slug": doc["slug"]}


@router.patch("/admin/rooms/{room_id}", summary="Redaguoti kambarį (+ ES sinchronizacija, cache invalidavimas)")
def update_room(room_id: str, body: RoomPatch, user: dict = Depends(MANAGER)):
    changes = body.model_dump(exclude_none=True)
    if "hints" in changes:
        changes["hints"] = hints_doc(body.hints)
    if "name" in changes:
        changes["slug"] = slugify(changes["name"])
    if not changes:
        raise HTTPException(400, "Nėra ką keisti")
    try:
        old = db.rooms.find_one_and_update({"_id": oid(room_id)}, {"$set": changes})
    except DuplicateKeyError:
        raise HTTPException(409, "Kambarys tokiu pavadinimu jau yra")
    if not old:
        raise HTTPException(404, "Kambarys nerastas")
    index_room(old["_id"])
    es.indices.refresh(index=ROOMS_INDEX)
    invalidate(f"cache:room:{old['slug']}", f"cache:room:{changes.get('slug', old['slug'])}")
    return {"ok": True}


@router.delete("/admin/rooms/{room_id}", summary="Išjungti kambarį (soft delete – istorija lieka)")
def deactivate_room(room_id: str, user: dict = Depends(MANAGER)):
    old = db.rooms.find_one_and_update({"_id": oid(room_id)}, {"$set": {"isActive": False}})
    if not old:
        raise HTTPException(404, "Kambarys nerastas")
    index_room(old["_id"])
    es.indices.refresh(index=ROOMS_INDEX)
    invalidate(f"cache:room:{old['slug']}")
    return {"ok": True}


@router.post("/admin/reindex", summary="Perindeksuoti visus kambarius į ElasticSearch")
def reindex(user: dict = Depends(ADMIN)):
    return {"indexed": reindex_all_rooms()}
