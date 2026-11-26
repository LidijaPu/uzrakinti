"""Atsiliepimai: tik žaidusiems ir tik vieną kartą."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from ..cache import invalidate
from ..db import db
from ..deps import current_user
from ..events import log_event
from ..services.search_sync import index_room
from ..utils import oid, serialize

router = APIRouter(tags=["reviews"])


class ReviewIn(BaseModel):
    bookingId: str
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=2000)


@router.post("/reviews", status_code=201, summary="Parašyti atsiliepimą (tik žaidusiems, 1 kartą)")
def create_review(body: ReviewIn, user: dict = Depends(current_user)):
    uid = oid(user["userId"])
    booking = db.bookings.find_one({"_id": oid(body.bookingId)})
    if not booking:
        raise HTTPException(404, "Rezervacija nerasta")
    if booking["status"] != "completed":
        raise HTTPException(400, "Atsiliepimą galima rašyti tik po žaidimo")
    played = booking["bookedBy"] == uid
    if not played and booking.get("teamId"):
        played = db.teams.count_documents({"_id": booking["teamId"], "members.userId": uid}, limit=1) > 0
    if not played:
        raise HTTPException(403, "Jūs nežaidėte šio žaidimo")

    try:
        db.reviews.insert_one({"roomId": booking["roomId"], "bookingId": booking["_id"], "userId": uid,
                               "rating": body.rating, "text": body.text, "createdAt": datetime.utcnow()})
    except DuplicateKeyError:
        raise HTTPException(409, "Šiam žaidimui atsiliepimą jau parašėte")

    # avg' = (avg*count + rating) / (count + 1), vienu atominiu update
    db.rooms.update_one({"_id": booking["roomId"]}, [{"$set": {"rating": {
        "count": {"$add": [{"$ifNull": ["$rating.count", 0]}, 1]},
        "avg": {"$round": [{"$divide": [
            {"$add": [{"$multiply": [{"$ifNull": ["$rating.avg", 0]}, {"$ifNull": ["$rating.count", 0]}]},
                      body.rating]},
            {"$add": [{"$ifNull": ["$rating.count", 0]}, 1]}]}, 2]},
    }}}])
    room = db.rooms.find_one({"_id": booking["roomId"]}, {"slug": 1, "rating": 1})
    invalidate(f"cache:room:{room['slug']}")
    index_room(room["_id"])
    log_event("review_created", user_id=user["userId"], room_id=str(booking["roomId"]),
              location_id=str(booking["locationId"]), booking_id=body.bookingId, value=body.rating)
    return {"ok": True, "roomRating": room["rating"]}


@router.get("/rooms/{room_id}/reviews", summary="Kambario atsiliepimai (naujausi)")
def room_reviews(room_id: str, limit: int = 20):
    rows = db.reviews.aggregate([
        {"$match": {"roomId": oid(room_id)}},
        {"$sort": {"createdAt": -1}},
        {"$limit": min(limit, 100)},
        {"$lookup": {"from": "users", "localField": "userId", "foreignField": "_id", "as": "u"}},
        {"$project": {"rating": 1, "text": 1, "createdAt": 1, "author": {"$arrayElemAt": ["$u.firstName", 0]}}},
    ])
    return [serialize(x) for x in rows]
