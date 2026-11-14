"""Rekordų lentelės – Redis Sorted Set (ZSET). Score = galutinis laikas sekundėmis (mažesnis geriau)."""
from fastapi import APIRouter

from ..db import db, r
from ..utils import oid

router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])


def record_result(room_id: str, team_id: str, final_time_sec: int, yyyymm: str) -> None:
    """Kviečiama baigus žaidimą. LT – atnaujinti tik jei naujas laikas GERESNIS (mažesnis)."""
    r.zadd(f"lb:room:{room_id}", {team_id: final_time_sec}, lt=True)
    r.zadd(f"lb:month:{yyyymm}", {f"{team_id}|{room_id}": final_time_sec}, lt=True)


@router.get("/rooms/{room_id}", summary="Kambario TOP N")
def room_top(room_id: str, n: int = 10):
    rows = r.zrange(f"lb:room:{room_id}", 0, n - 1, withscores=True)
    names = {str(t["_id"]): t["name"] for t in
             db.teams.find({"_id": {"$in": [oid(t) for t, _ in rows]}}, {"name": 1})}
    return [{"place": i + 1, "teamId": t, "team": names.get(t, "?"), "timeSec": int(s)}
            for i, (t, s) in enumerate(rows)]
