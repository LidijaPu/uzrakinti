"""Rezervacijos – svarbiausia vientisumo vieta.

Dviejų etapų procesas:
  1. POST /bookings/hold    – laikas užlaikomas Redis'e 10 min. (SET NX EX). Kitas žaidėjas mato „held“.
  2. POST /bookings/confirm – įrašoma į MongoDB. Unikalus dalinis indeksas {roomId, startAt}
                              (tik active=true) yra GALUTINĖ garantija: net jei Redis raktas
                              pasibaigė, du aktyvūs užsakymai tam pačiam laikui neįmanomi.
"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from ..cache import invalidate
from ..config import settings
from ..db import db, r
from ..deps import current_user
from ..events import log_event
from ..utils import oid, serialize
from .rooms import room_slots

router = APIRouter(prefix="/bookings", tags=["bookings"])


class SlotIn(BaseModel):
    roomId: str
    startAt: datetime
    playersCount: int = Field(ge=1, le=12)
    teamId: str | None = None


class ConfirmIn(BaseModel):
    roomId: str
    startAt: datetime
    promoCode: str | None = None


def hold_key(room_id: str, start_at: datetime) -> str:
    return f"hold:{room_id}:{start_at.replace(tzinfo=None).isoformat()}"


@router.post("/hold", summary="1 etapas: laikinai užlaikyti laiką (Redis, 10 min.)")
def hold(body: SlotIn, user: dict = Depends(current_user)):
    room = db.rooms.find_one({"_id": oid(body.roomId), "isActive": True})
    if not room:
        raise HTTPException(404, "Kambarys nerastas")
    start = body.startAt.replace(tzinfo=None)
    if start not in room_slots(room, start.date()) or start <= datetime.now():
        raise HTTPException(400, "Toks laikas neegzistuoja arba jau praėjo")
    if not room["minPlayers"] <= body.playersCount <= room["maxPlayers"]:
        raise HTTPException(400, f"Žaidėjų skaičius turi būti {room['minPlayers']}–{room['maxPlayers']}")
    if db.bookings.count_documents({"roomId": room["_id"], "startAt": start, "active": True}, limit=1):
        raise HTTPException(409, "Laikas jau užimtas")

    payload = json.dumps({"userId": user["userId"], "playersCount": body.playersCount,
                          "teamId": body.teamId})
    # SET NX – atominis: tik VIENAS klientas gali sukurti raktą
    if not r.set(hold_key(body.roomId, start), payload, nx=True, ex=settings.hold_ttl):
        raise HTTPException(409, "Šį laiką šiuo metu rezervuoja kitas žaidėjas")

    log_event("booking_held", user_id=user["userId"], room_id=body.roomId,
              location_id=str(room["locationId"]), meta={"startAt": start})
    return {"heldUntilSec": settings.hold_ttl}


@router.post("/confirm", status_code=201, summary="2 etapas: patvirtinti (įrašoma į MongoDB)")
def confirm(body: ConfirmIn, user: dict = Depends(current_user)):
    start = body.startAt.replace(tzinfo=None)
    key = hold_key(body.roomId, start)
    raw = r.get(key)
    if raw is None:
        raise HTTPException(410, "Užlaikymo laikas baigėsi – pasirinkite laiką iš naujo")
    held = json.loads(raw)
    if held["userId"] != user["userId"]:
        raise HTTPException(409, "Laiką užlaikė kitas žaidėjas")

    room = db.rooms.find_one({"_id": oid(body.roomId)})
    price = float(room["pricePerPlayer"]) * held["playersCount"]
    # TODO (2 sav.): promo kodas – find_one_and_update su usedCount < maxUses
    # TODO (3 sav.): dovanų kuponas – transakcija (kuponas + rezervacija)

    booking = {
        "roomId": room["_id"], "locationId": room["locationId"],
        "teamId": oid(held["teamId"]) if held.get("teamId") else None,
        "bookedBy": oid(user["userId"]), "startAt": start,
        "endAt": start + timedelta(minutes=room["durationMin"]),
        "playersCount": held["playersCount"], "status": "confirmed", "active": True,
        "totalPrice": price, "promoCode": body.promoCode,
        "payment": {"method": "card", "amount": price, "paidAt": datetime.utcnow()},
        "createdAt": datetime.utcnow(),
    }
    try:
        res = db.bookings.insert_one(booking)
    except DuplicateKeyError:
        raise HTTPException(409, "Laikas jau užimtas")  # unikalus indeksas sustabdė dublį
    finally:
        r.delete(key)

    invalidate(f"cache:availability:{body.roomId}:{start.date().isoformat()}")
    log_event("booking_confirmed", user_id=user["userId"], room_id=body.roomId,
              location_id=str(room["locationId"]), booking_id=str(res.inserted_id),
              value=price, meta={"startAt": start, "players": held["playersCount"]})
    return {"id": str(res.inserted_id), "totalPrice": price}


@router.post("/{booking_id}/cancel", summary="Atšaukti rezervaciją (active=false atlaisvina laiką)")
def cancel(booking_id: str, user: dict = Depends(current_user)):
    b = db.bookings.find_one_and_update(
        {"_id": oid(booking_id), "bookedBy": oid(user["userId"]), "status": "confirmed",
         "startAt": {"$gt": datetime.now()}},
        {"$set": {"status": "cancelled", "active": False}})
    if not b:
        raise HTTPException(404, "Rezervacija nerasta arba jos atšaukti nebegalima")
    invalidate(f"cache:availability:{b['roomId']}:{b['startAt'].date().isoformat()}")
    log_event("booking_cancelled", user_id=user["userId"], room_id=str(b["roomId"]),
              location_id=str(b["locationId"]), booking_id=booking_id)
    return {"ok": True}


@router.get("/mine", summary="Mano rezervacijos")
def my_bookings(user: dict = Depends(current_user)):
    cur = db.bookings.find({"bookedBy": oid(user["userId"])}).sort("startAt", -1).limit(50)
    return [serialize(b) for b in cur]
