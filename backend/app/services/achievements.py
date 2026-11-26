"""Žaidėjų statistika (users.stats) ir pasiekimai, atnaujinami baigus žaidimą."""
from datetime import datetime

from bson import ObjectId

from ..db import db

ACHIEVEMENTS = {
    "first_escape": "Pirmasis pabėgimas",
    "fast_40": "Pabėgo per < 40 min.",
    "no_hints": "Be užuominų",
    "five_rooms": "5 skirtingi kambariai",
    "ten_games": "10 žaidimų",
}


def update_players_after_game(user_ids: list[ObjectId], room_id: ObjectId, escaped: bool,
                              time_sec: int, hints: int) -> dict[str, list[str]]:
    if not user_ids:
        return {}
    db.users.update_many(
        {"_id": {"$in": user_ids}},
        {"$inc": {"stats.games": 1, "stats.escapes": 1 if escaped else 0},
         "$addToSet": {"stats.rooms": room_id}},
    )
    earned: dict[str, list[str]] = {}
    now = datetime.utcnow()
    for u in db.users.find({"_id": {"$in": user_ids}}, {"stats": 1}):
        st = u.get("stats", {})
        codes = []
        if escaped and st.get("escapes", 0) >= 1:
            codes.append("first_escape")
        if escaped and time_sec < 40 * 60:
            codes.append("fast_40")
        if escaped and hints == 0:
            codes.append("no_hints")
        if len(st.get("rooms", [])) >= 5:
            codes.append("five_rooms")
        if st.get("games", 0) >= 10:
            codes.append("ten_games")
        for code in codes:
            # tas pats pasiekimas tik vieną kartą
            res = db.users.update_one(
                {"_id": u["_id"], "achievements.code": {"$ne": code}},
                {"$push": {"achievements": {"code": code, "title": ACHIEVEMENTS[code], "earnedAt": now}}},
            )
            if res.modified_count:
                earned.setdefault(str(u["_id"]), []).append(code)
    return earned
