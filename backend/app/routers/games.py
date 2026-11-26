"""Žaidimų valdymas (vedėjo panelė) ir kambario ekranas per WebSocket. Žr. docs/vientisumas.md."""
import asyncio
import json
import time
from datetime import date, datetime, time as dtime, timedelta

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .. import db as dbmod
from ..db import db, r
from ..deps import require_role
from ..events import log_event
from ..services.achievements import update_players_after_game
from ..utils import oid, serialize
from .leaderboards import record_result

router = APIRouter(tags=["games"])
STAFF = require_role("gameMaster", "manager", "admin")
GAME_TTL = 3 * 3600


class StartIn(BaseModel):
    bookingId: str


class HintIn(BaseModel):
    hintId: str


class FinishIn(BaseModel):
    escaped: bool


def screen_channel(room_id: str) -> str:
    return f"room:{room_id}:screen"


def publish(room_id: str, message: dict) -> None:
    r.publish(screen_channel(room_id), json.dumps(message, default=str, ensure_ascii=False))


def live_state(sid: str) -> dict | None:
    h = r.hgetall(f"game:{sid}")
    if not h:
        return None
    started = float(h["startedAt"])
    return {"sessionId": sid, "roomId": h["roomId"], "status": h["status"],
            "elapsedSec": int(time.time() - started), "durationSec": int(h["durationSec"]),
            "hintsUsed": int(h["hintsUsed"]), "penaltySec": int(h["penaltySec"])}


@router.get("/games/today", summary="Vedėjo panelė: šiandienos rezervacijos ir žaidimų būsenos")
def today(locationId: str | None = None, user: dict = Depends(STAFF)):
    start = datetime.combine(date.today(), dtime.min)
    match: dict = {"startAt": {"$gte": start, "$lt": start + timedelta(days=1)},
                   "status": {"$in": ["confirmed", "completed"]}}
    if locationId:
        match["locationId"] = oid(locationId)
    rows = list(db.bookings.aggregate([
        {"$match": match},
        {"$sort": {"startAt": 1}},
        {"$lookup": {"from": "rooms", "localField": "roomId", "foreignField": "_id", "as": "room"}},
        {"$lookup": {"from": "teams", "localField": "teamId", "foreignField": "_id", "as": "team"}},
        {"$lookup": {"from": "game_sessions", "localField": "_id", "foreignField": "bookingId", "as": "session"}},
        {"$project": {"startAt": 1, "playersCount": 1, "status": 1, "roomId": 1,
                      "room": {"$arrayElemAt": ["$room.name", 0]}, "team": {"$arrayElemAt": ["$team.name", 0]},
                      "sessionId": {"$arrayElemAt": ["$session._id", 0]},
                      "finishedAt": {"$arrayElemAt": ["$session.finishedAt", 0]},
                      "escaped": {"$arrayElemAt": ["$session.escaped", 0]}}},
    ]))
    return [serialize(b) for b in rows]


@router.post("/games/start", status_code=201, summary="Pradėti žaidimą pagal rezervaciją")
def start_game(body: StartIn, user: dict = Depends(STAFF)):
    booking = db.bookings.find_one({"_id": oid(body.bookingId), "status": "confirmed", "active": True})
    if not booking:
        raise HTTPException(404, "Patvirtinta rezervacija nerasta")
    if abs((booking["startAt"] - datetime.now()).total_seconds()) > 24 * 3600:
        raise HTTPException(400, "Žaidimą galima pradėti tik rezervacijos dieną")
    room_id = str(booking["roomId"])
    if r.exists(f"room:{room_id}:game"):
        raise HTTPException(409, "Šiame kambaryje jau vyksta žaidimas")
    room = db.rooms.find_one({"_id": booking["roomId"]}, {"durationMin": 1, "name": 1})

    now = datetime.utcnow()
    try:
        # unikalus bookingId – vienai rezervacijai vienas žaidimas
        res = db.game_sessions.insert_one({
            "bookingId": booking["_id"], "roomId": booking["roomId"], "teamId": booking.get("teamId"),
            "gameMasterId": oid(user["userId"]), "startedAt": now, "hintsUsed": [],
        })
    except DuplicateKeyError:
        raise HTTPException(409, "Šios rezervacijos žaidimas jau buvo pradėtas")
    sid = str(res.inserted_id)

    key = f"game:{sid}"
    pipe = r.pipeline()
    pipe.hset(key, mapping={"roomId": room_id, "bookingId": body.bookingId, "status": "running",
                            "startedAt": time.time(), "durationSec": room["durationMin"] * 60,
                            "hintsUsed": 0, "penaltySec": 0})
    pipe.expire(key, GAME_TTL)
    pipe.set(f"room:{room_id}:game", sid, ex=GAME_TTL)
    pipe.execute()

    publish(room_id, {"type": "started", "sessionId": sid, "room": room["name"],
                      "durationSec": room["durationMin"] * 60})
    log_event("game_started", user_id=str(booking["bookedBy"]), room_id=room_id,
              location_id=str(booking["locationId"]), booking_id=body.bookingId, session_id=sid)
    return {"sessionId": sid, "durationSec": room["durationMin"] * 60}


@router.get("/games/{sid}", summary="Žaidimo būsena + kambario užuominų sąrašas vedėjui")
def get_game(sid: str, user: dict = Depends(STAFF)):
    session = db.game_sessions.find_one({"_id": oid(sid)})
    if not session:
        raise HTTPException(404, "Žaidimas nerastas")
    room = db.rooms.find_one({"_id": session["roomId"]}, {"name": 1, "hints": 1})
    sent = {h["hintId"] for h in session.get("hintsUsed", [])}
    return {
        "live": live_state(sid),
        "session": serialize(session),
        "room": room["name"],
        "hints": [{**h, "sent": h["hintId"] in sent} for h in sorted(room.get("hints", []), key=lambda h: h["order"])],
    }


@router.post("/games/{sid}/hints", summary="Išsiųsti užuominą į kambario ekraną (Redis Pub/Sub)")
def send_hint(sid: str, body: HintIn, user: dict = Depends(STAFF)):
    state = live_state(sid)
    if not state or state["status"] != "running":
        raise HTTPException(409, "Žaidimas nevyksta")
    room = db.rooms.find_one({"_id": oid(state["roomId"])}, {"hints": 1})
    hint = next((h for h in room.get("hints", []) if h["hintId"] == body.hintId), None)
    if not hint:
        raise HTTPException(404, "Tokios užuominos nėra")

    # SADD grąžina 0, jei užuomina jau išsiųsta
    if not r.sadd(f"game:{sid}:hints", body.hintId):
        raise HTTPException(409, "Ši užuomina jau išsiųsta")
    r.expire(f"game:{sid}:hints", GAME_TTL)
    penalty = hint.get("penaltySec", 120)
    r.hincrby(f"game:{sid}", "hintsUsed", 1)
    r.hincrby(f"game:{sid}", "penaltySec", penalty)

    at_sec = state["elapsedSec"]
    db.game_sessions.update_one({"_id": oid(sid), "hintsUsed.hintId": {"$ne": body.hintId}},
                                {"$push": {"hintsUsed": {"hintId": body.hintId, "atSec": at_sec}}})
    publish(state["roomId"], {"type": "hint", "hintId": body.hintId, "text": hint["text"],
                              "penaltySec": penalty, "atSec": at_sec})
    log_event("hint_used", room_id=state["roomId"], session_id=sid, value=at_sec,
              meta={"hintId": body.hintId})
    return {"ok": True, "atSec": at_sec, "penaltySec": penalty}


@router.post("/games/{sid}/finish", summary="Baigti žaidimą: rezultatas, rekordai, statistika, pasiekimai")
def finish_game(sid: str, body: FinishIn, user: dict = Depends(STAFF)):
    state = live_state(sid)
    session = db.game_sessions.find_one({"_id": oid(sid)})
    if not session:
        raise HTTPException(404, "Žaidimas nerastas")
    duration = state["durationSec"] if state else 3600
    elapsed = min(state["elapsedSec"], duration) if state else int((datetime.utcnow() - session["startedAt"]).total_seconds())
    hints = len(session.get("hintsUsed", []))
    penalty = state["penaltySec"] if state else hints * 120
    time_sec = elapsed if body.escaped else duration
    final = time_sec + penalty

    # baigti galima tik vieną kartą
    done = db.game_sessions.find_one_and_update(
        {"_id": oid(sid), "finishedAt": {"$exists": False}},
        {"$set": {"finishedAt": datetime.utcnow(), "escaped": body.escaped, "timeSec": time_sec,
                  "penaltySec": penalty, "finalTimeSec": final}},
        return_document=ReturnDocument.AFTER)
    if not done:
        raise HTTPException(409, "Žaidimas jau baigtas")

    booking = db.bookings.find_one_and_update({"_id": session["bookingId"]}, {"$set": {"status": "completed"}})
    room_id = str(session["roomId"])

    if body.escaped and session.get("teamId"):
        record_result(room_id, str(session["teamId"]), final, datetime.now().strftime("%Y%m"), hints)

    member_ids = [booking["bookedBy"]]
    if session.get("teamId"):
        team = db.teams.find_one({"_id": session["teamId"]}, {"members.userId": 1})
        if team:
            member_ids = [m["userId"] for m in team["members"]]
    earned = update_players_after_game(member_ids, session["roomId"], body.escaped, time_sec, hints)

    r.delete(f"game:{sid}", f"game:{sid}:hints", f"room:{room_id}:game")
    publish(room_id, {"type": "finished", "escaped": body.escaped, "timeSec": time_sec,
                      "penaltySec": penalty, "finalTimeSec": final})
    log_event("game_finished", user_id=str(booking["bookedBy"]), room_id=room_id,
              location_id=str(booking["locationId"]), booking_id=str(booking["_id"]), session_id=sid,
              value=final, meta={"escaped": body.escaped, "hints": hints, "players": booking["playersCount"]})
    return {"escaped": body.escaped, "timeSec": time_sec, "penaltySec": penalty,
            "finalTimeSec": final, "achievements": earned}


@router.websocket("/ws/rooms/{room_id}")
async def room_screen(ws: WebSocket, room_id: str):
    await ws.accept()
    ar = dbmod.async_redis()
    pubsub = ar.pubsub()
    await pubsub.subscribe(screen_channel(room_id))
    try:
        sid = await ar.get(f"room:{room_id}:game")
        if sid:
            h = await ar.hgetall(f"game:{sid}")
            if h:
                await ws.send_json({"type": "state", "sessionId": sid,
                                    "elapsedSec": int(time.time() - float(h["startedAt"])),
                                    "durationSec": int(h["durationSec"]),
                                    "hintsUsed": int(h["hintsUsed"]), "penaltySec": int(h["penaltySec"])})

        async def forward():
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    await ws.send_text(msg["data"])

        async def wait_disconnect():
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(forward()), asyncio.create_task(wait_disconnect())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in tasks:
            t.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(screen_channel(room_id))
        await pubsub.aclose()
        await ar.aclose()


@router.get("/screen/{room_id}", response_class=HTMLResponse, include_in_schema=False)
def screen_page(room_id: str):
    """Paprastas kambario ekranas demo (kol nėra frontend'o)."""
    return SCREEN_HTML.replace("__ROOM__", room_id)


SCREEN_HTML = """<!doctype html><html lang="lt"><head><meta charset="utf-8"><title>Kambario ekranas</title>
<style>body{background:#111;color:#eee;font-family:system-ui;text-align:center;margin:0;padding:40px}
#t{font-size:120px;font-variant-numeric:tabular-nums;margin:20px}#s{color:#999}
.h{background:#2a2a2a;border-left:6px solid #f5b301;margin:12px auto;max-width:800px;padding:16px;font-size:26px;text-align:left}</style>
</head><body><div id="s">Laukiama žaidimo…</div><div id="t">60:00</div><div id="hints"></div>
<script>
let end=null,timer=null;const t=document.getElementById('t'),s=document.getElementById('s'),H=document.getElementById('hints');
function tick(){const left=Math.max(0,Math.round((end-Date.now())/1000));t.textContent=String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0');}
function run(dur,el){end=Date.now()+(dur-el)*1000;clearInterval(timer);timer=setInterval(tick,250);tick();s.textContent='Žaidimas vyksta';}
const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/rooms/__ROOM__');
ws.onmessage=e=>{const m=JSON.parse(e.data);
 if(m.type==='started'){H.innerHTML='';run(m.durationSec,0);}
 if(m.type==='state'){run(m.durationSec,m.elapsedSec);}
 if(m.type==='hint'){const d=document.createElement('div');d.className='h';d.textContent='💡 '+m.text;H.prepend(d);}
 if(m.type==='finished'){clearInterval(timer);s.textContent=m.escaped?'🎉 Pabėgote!':'⏰ Laikas baigėsi';}};
ws.onclose=()=>{s.textContent='Ryšys nutrūko – perkraukite puslapį';};
</script></body></html>"""
