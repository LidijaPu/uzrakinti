"""Analitikos ataskaitos iš ClickHouse. Rezultatai cache'uojami Redis'e (sunkūs skaičiavimai)."""
from datetime import date

from fastapi import APIRouter, Depends

from ..cache import cached
from ..db import ch, db
from ..deps import require_role

router = APIRouter(prefix="/reports", tags=["reports"],
                   dependencies=[Depends(require_role("manager", "admin"))])
TTL = 600


def with_room_names(rows: list[dict]) -> list[dict]:
    """Kambarių pavadinimai iš MongoDB (ClickHouse saugo tik roomId)."""
    from bson import ObjectId
    ids = [ObjectId(x["roomId"]) for x in rows if ObjectId.is_valid(x.get("roomId", ""))]
    names = {str(x["_id"]): x["name"] for x in db.rooms.find({"_id": {"$in": ids}}, {"name": 1})}
    return [{**x, "room": names.get(x.get("roomId"), "?")} for x in rows]


def query(sql: str, params: dict) -> list[dict]:
    res = ch().query(sql, parameters=params)
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


@router.get("/revenue", summary="Pajamos per laikotarpį pagal filialą")
def revenue(date_from: date, date_to: date, granularity: str = "day"):
    fn = {"day": "toDate", "week": "toMonday", "month": "toStartOfMonth"}.get(granularity, "toDate")
    sql = f"""
        SELECT {fn}(ts) AS period, locationId, sum(value) AS revenue, count() AS bookings
        FROM events
        WHERE eventType = 'booking_confirmed' AND toDate(ts) BETWEEN {{f:Date}} AND {{t:Date}}
        GROUP BY period, locationId ORDER BY period"""
    key = f"cache:report:revenue:{date_from}:{date_to}:{granularity}"
    return cached(key, TTL, lambda: query(sql, {"f": date_from, "t": date_to}))


@router.get("/occupancy", summary="Užimtumo heatmap: savaitės diena × valanda")
def occupancy(location_id: str, date_from: date, date_to: date):
    sql = """
        SELECT toDayOfWeek(s) AS dow, toHour(s) AS hour, count() AS bookings
        FROM (SELECT parseDateTimeBestEffort(JSONExtractString(meta, 'startAt')) AS s
              FROM events
              WHERE eventType = 'booking_confirmed' AND locationId = {loc:String}
                AND toDate(ts) BETWEEN {f:Date} AND {t:Date})
        GROUP BY dow, hour ORDER BY dow, hour"""
    key = f"cache:report:occupancy:{location_id}:{date_from}:{date_to}"
    return cached(key, TTL, lambda: query(sql, {"loc": location_id, "f": date_from, "t": date_to}))


@router.get("/escape-rate", summary="Pabėgimo procentas ir vidutinis laikas pagal kambarį")
def escape_rate(date_from: date, date_to: date):
    sql = """
        SELECT roomId,
               count() AS games,
               countIf(JSONExtractBool(meta, 'escaped')) AS escapes,
               round(escapes / games * 100, 1) AS escapePct,
               round(avgIf(value, JSONExtractBool(meta, 'escaped')) / 60, 1) AS avgEscapeMin,
               round(avg(JSONExtractInt(meta, 'hints')), 2) AS avgHints
        FROM events
        WHERE eventType = 'game_finished' AND toDate(ts) BETWEEN {f:Date} AND {t:Date}
        GROUP BY roomId ORDER BY escapePct"""
    key = f"cache:report:escape-rate:{date_from}:{date_to}"
    return cached(key, TTL, lambda: with_room_names(query(sql, {"f": date_from, "t": date_to})))


@router.get("/hints", summary="Užuominos: kurios naudojamos dažniausiai ir kelintą minutę")
def hints(date_from: date, date_to: date, room_id: str | None = None):
    sql = """
        SELECT roomId, JSONExtractString(meta, 'hintId') AS hintId,
               count() AS used, round(avg(value) / 60, 1) AS avgMinute
        FROM events
        WHERE eventType = 'hint_used' AND toDate(ts) BETWEEN {f:Date} AND {t:Date}
          AND ({room:String} = '' OR roomId = {room:String})
        GROUP BY roomId, hintId ORDER BY roomId, hintId"""
    key = f"cache:report:hints:{date_from}:{date_to}:{room_id or ''}"
    return cached(key, TTL, lambda: with_room_names(
        query(sql, {"f": date_from, "t": date_to, "room": room_id or ""})))


@router.get("/funnel", summary="Konversijos piltuvėlis: peržiūra → užlaikymas → rezervacija → žaidimas")
def funnel(date_from: date, date_to: date):
    # windowFunnel: kiek žingsnių iš eilės vartotojas pasiekė per 30 d.
    sql = """
        SELECT level, count() AS users
        FROM (
            SELECT userId,
                   windowFunnel(2592000)(ts, eventType = 'room_view', eventType = 'booking_held',
                                         eventType = 'booking_confirmed', eventType = 'game_finished') AS level
            FROM events
            WHERE userId != '' AND toDate(ts) BETWEEN {f:Date} AND {t:Date}
              AND eventType IN ('room_view', 'booking_held', 'booking_confirmed', 'game_finished')
            GROUP BY userId)
        GROUP BY level ORDER BY level"""

    def compute():
        by_level = {row["level"]: row["users"] for row in query(sql, {"f": date_from, "t": date_to})}
        steps = ["Peržiūrėjo kambarį", "Užlaikė laiką", "Rezervavo", "Sužaidė"]
        reached = [sum(n for lvl, n in by_level.items() if lvl >= i + 1) for i in range(4)]
        return [{"step": s, "users": n, "pctOfFirst": round(n / reached[0] * 100, 1) if reached[0] else 0}
                for s, n in zip(steps, reached)]

    return cached(f"cache:report:funnel:{date_from}:{date_to}", TTL, compute)


@router.get("/loyalty", summary="Lojalumas: kiek klientų rezervavo 1, 2, 3–5, 6+ kartus")
def loyalty(date_from: date, date_to: date):
    sql = """
        SELECT multiIf(n = 1, '1', n = 2, '2', n <= 5, '3–5', '6+') AS bucket,
               count() AS customers, sum(revenue) AS revenue
        FROM (SELECT userId, count() AS n, sum(value) AS revenue
              FROM events
              WHERE eventType = 'booking_confirmed' AND toDate(ts) BETWEEN {f:Date} AND {t:Date}
              GROUP BY userId)
        GROUP BY bucket ORDER BY min(n)"""
    key = f"cache:report:loyalty:{date_from}:{date_to}"
    return cached(key, TTL, lambda: query(sql, {"f": date_from, "t": date_to}))


@router.get("/age-groups", summary="Aktyvumas pagal amžiaus grupes (rezervacijos ir pajamos)")
def age_groups(date_from: date, date_to: date):
    sql = """
        SELECT multiIf(age < 18, '<18', age < 25, '18–24', age < 35, '25–34', age < 50, '35–49', '50+') AS ageGroup,
               count() AS bookings, uniqExact(b.userId) AS customers, round(sum(b.value), 2) AS revenue
        FROM (SELECT userId, value, ts FROM events
              WHERE eventType = 'booking_confirmed' AND toDate(ts) BETWEEN {f:Date} AND {t:Date}) AS b
        INNER JOIN (SELECT userId, toYear(now()) - JSONExtractInt(meta, 'birthYear') AS age
                    FROM events WHERE eventType = 'register') AS u ON b.userId = u.userId
        GROUP BY ageGroup ORDER BY ageGroup"""
    key = f"cache:report:age-groups:{date_from}:{date_to}"
    return cached(key, TTL, lambda: query(sql, {"f": date_from, "t": date_to}))


@router.get("/searches", summary="Populiariausios paieškos frazės ir paieškos be rezultatų")
def searches(date_from: date, date_to: date, limit: int = 15):
    sql = """
        SELECT lower(JSONExtractString(meta, 'q')) AS q, count() AS searches,
               countIf(value = 0) AS zeroResults, round(avg(value), 1) AS avgResults
        FROM events
        WHERE eventType = 'search' AND toDate(ts) BETWEEN {f:Date} AND {t:Date} AND q != ''
        GROUP BY q ORDER BY searches DESC LIMIT {n:UInt32}"""
    key = f"cache:report:searches:{date_from}:{date_to}:{limit}"
    return cached(key, TTL, lambda: query(sql, {"f": date_from, "t": date_to, "n": limit}))
