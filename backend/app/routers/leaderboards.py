"""Rekordų lentelės – Redis Sorted Set (ZSET). Score = galutinis laikas sekundėmis (mažesnis geriau)."""
from fastapi import APIRouter

from ..db import db, r
from ..utils import oid

router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])


def record_result(room_id: str, team_id: str, final_time_sec: int, yyyymm: str, hints: int = 0) -> None:
    """Kviečiama baigus žaidimą. LT – atnaujinti tik jei naujas laikas GERESNIS (mažesnis)."""
    r.zadd(f"lb:room:{room_id}", {team_id: final_time_sec}, lt=True)
    r.zadd(f"lb:month:{yyyymm}", {f"{team_id}|{room_id}": final_time_sec}, lt=True)
    if hints == 0:
        r.zadd("lb:nohints", {f"{team_id}|{room_id}": final_time_sec}, lt=True)


def _team_names(team_ids: list[str]) -> dict[str, str]:
    return {str(t["_id"]): t["name"] for t in
            db.teams.find({"_id": {"$in": [oid(t) for t in team_ids]}}, {"name": 1})}


def _room_names(room_ids: list[str]) -> dict[str, str]:
    return {str(x["_id"]): x["name"] for x in
            db.rooms.find({"_id": {"$in": [oid(x) for x in room_ids]}}, {"name": 1})}


def _team_room_rows(key: str, n: int) -> list[dict]:
    """ZSET narys = "teamId|roomId"."""
    rows = r.zrange(key, 0, n - 1, withscores=True)
    pairs = [m.split("|") for m, _ in rows]
    teams = _team_names([t for t, _ in pairs])
    rooms = _room_names([rm for _, rm in pairs])
    return [{"place": i + 1, "teamId": t, "team": teams.get(t, "?"), "roomId": rm,
             "room": rooms.get(rm, "?"), "timeSec": int(s)}
            for i, ((t, rm), (_, s)) in enumerate(zip(pairs, rows))]


@router.get("/rooms/{room_id}", summary="Kambario TOP N")
def room_top(room_id: str, n: int = 10):
    rows = r.zrange(f"lb:room:{room_id}", 0, n - 1, withscores=True)
    names = _team_names([t for t, _ in rows])
    return [{"place": i + 1, "teamId": t, "team": names.get(t, "?"), "timeSec": int(s)}
            for i, (t, s) in enumerate(rows)]


@router.get("/month/{yyyymm}", summary="Mėnesio TOP (visi kambariai), pvz. 202611")
def month_top(yyyymm: str, n: int = 10):
    return _team_room_rows(f"lb:month:{yyyymm}", n)


@router.get("/no-hints", summary="„Be užuominų“ lyga – geriausi laikai be nė vienos užuominos")
def no_hints_top(n: int = 10):
    return _team_room_rows("lb:nohints", n)
