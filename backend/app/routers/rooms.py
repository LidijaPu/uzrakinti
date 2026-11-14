from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException

from ..cache import cached
from ..db import db, r
from ..events import log_event
from ..utils import oid, serialize

router = APIRouter(prefix="/rooms", tags=["rooms"])


def room_slots(room: dict, day: date) -> list[datetime]:
    """Kambario laikai konkrečiai dienai (laikas saugomas kaip vietinis, be laiko juostos)."""
    return [datetime.combine(day, time.fromisoformat(t)) for t in room["slotTimes"]]


@router.get("", summary="Kambarių sąrašas (filtrai: miestas, tema)")
def list_rooms(city: str | None = None, theme: str | None = None):
    match: dict = {"isActive": True}
    if theme:
        match["theme"] = theme
    if city:
        loc_ids = [l["_id"] for l in db.locations.find({"city": city}, {"_id": 1})]
        match["locationId"] = {"$in": loc_ids}
    rooms = db.rooms.find(match, {"hints": 0}).sort("name", 1)
    return [serialize(x) for x in rooms]


@router.get("/{slug}", summary="Kambario informacija (Redis cache 10 min.)")
def get_room(slug: str, userId: str = ""):
    def compute():
        room = db.rooms.find_one({"slug": slug}, {"hints": 0})
        if not room:
            return None
        room["location"] = serialize(db.locations.find_one({"_id": room["locationId"]}))
        return serialize(room)

    room = cached(f"cache:room:{slug}", 600, compute)
    if room is None:
        raise HTTPException(404, "Kambarys nerastas")
    log_event("room_view", user_id=userId, room_id=room["id"], location_id=room["locationId"])
    return room


@router.get("/{room_id}/availability", summary="Laisvi laikai dienai")
def availability(room_id: str, day: date):
    """Užimti (patvirtinti) laikai – iš MongoDB, cache'uojama 60 s.
    Užlaikyti (hold) laikai – visada tikrinami gyvai Redis'e (MGET), nes keičiasi kas sekundę."""
    rid = oid(room_id)
    room = db.rooms.find_one({"_id": rid}, {"slotTimes": 1})
    if not room:
        raise HTTPException(404, "Kambarys nerastas")

    def compute_booked():
        start = datetime.combine(day, time.min)
        cur = db.bookings.find({"roomId": rid, "active": True,
                                "startAt": {"$gte": start, "$lt": start + timedelta(days=1)}},
                               {"startAt": 1})
        return [b["startAt"].isoformat() for b in cur]

    booked = set(cached(f"cache:availability:{room_id}:{day.isoformat()}", 60, compute_booked))
    slots = room_slots(room, day)
    held = r.mget([f"hold:{room_id}:{s.isoformat()}" for s in slots]) if slots else []
    now = datetime.now()
    return [{
        "startAt": s.isoformat(),
        "status": "past" if s <= now else "booked" if s.isoformat() in booked
        else "held" if h is not None else "free",
    } for s, h in zip(slots, held)]
