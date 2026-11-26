"""Žaidėjo profilis, pasiekimai ir duomenų eksportas."""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..db import db
from ..deps import current_user
from ..events import log_event
from ..utils import oid, serialize

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/profile", summary="Mano profilis su statistika")
def profile(user: dict = Depends(current_user)):
    u = db.users.find_one({"_id": oid(user["userId"])}, {"passwordHash": 0})
    if not u:
        raise HTTPException(404, "Vartotojas nerastas")
    out = serialize(u)
    stats = u.get("stats", {})
    out["stats"] = {"games": stats.get("games", 0), "escapes": stats.get("escapes", 0),
                    "distinctRooms": len(stats.get("rooms", []))}
    return out


@router.get("/achievements", summary="Mano pasiekimai")
def achievements(user: dict = Depends(current_user)):
    u = db.users.find_one({"_id": oid(user["userId"])}, {"achievements": 1})
    return u.get("achievements", []) if u else []


@router.get("/export", summary="Atsisiųsti visus savo duomenis (JSON archyvas)")
def export(user: dict = Depends(current_user)):
    uid = oid(user["userId"])
    me = db.users.find_one({"_id": uid}, {"passwordHash": 0})
    teams = list(db.teams.find({"members.userId": uid}))
    team_ids = [t["_id"] for t in teams]
    bookings = list(db.bookings.find({"$or": [{"bookedBy": uid}, {"teamId": {"$in": team_ids}}]})
                    .sort("startAt", -1))
    sessions = list(db.game_sessions.find({"bookingId": {"$in": [b["_id"] for b in bookings]}},
                                          {"hintsUsed": 0}))
    reviews = list(db.reviews.find({"userId": uid}))
    archive = {
        "exportedAt": datetime.utcnow(),
        "profile": serialize(me),
        "teams": [serialize(t) for t in teams],
        "bookings": [serialize(b) for b in bookings],
        "games": [serialize(s) for s in sessions],
        "reviews": [serialize(x) for x in reviews],
    }
    log_event("data_export", user_id=user["userId"], value=len(bookings))
    body = json.dumps(archive, default=str, ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="uzrakinti-mano-duomenys.json"'})
