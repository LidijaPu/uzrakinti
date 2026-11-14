"""MongoDB → ElasticSearch sinchronizacija. MongoDB yra tiesos šaltinis, ES – iš jo gaunama kopija."""
from bson import ObjectId

from ..db import ROOMS_INDEX, db, es


def room_to_doc(room: dict, location: dict) -> dict:
    lng, lat = location["geo"]["coordinates"]
    return {
        "name": room["name"], "description": room.get("description", ""), "slug": room["slug"],
        "theme": room["theme"], "tags": room.get("tags", []),
        "city": location["city"], "locationName": location["name"],
        "difficulty": room["difficulty"], "minPlayers": room["minPlayers"],
        "maxPlayers": room["maxPlayers"], "durationMin": room["durationMin"],
        "price": float(room["pricePerPlayer"]),
        "rating": float(room.get("rating", {}).get("avg", 0)),
        "location": {"lat": lat, "lon": lng}, "isActive": room["isActive"],
    }


def index_room(room_id: ObjectId) -> None:
    room = db.rooms.find_one({"_id": room_id})
    location = db.locations.find_one({"_id": room["locationId"]})
    es.index(index=ROOMS_INDEX, id=str(room_id), document=room_to_doc(room, location))


def reindex_all_rooms() -> int:
    n = 0
    for room in db.rooms.find({}, {"_id": 1}):
        index_room(room["_id"])
        n += 1
    es.indices.refresh(index=ROOMS_INDEX)
    return n
