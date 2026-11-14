"""Analitikos ataskaitos iš ClickHouse. Rezultatai cache'uojami Redis'e (sunkūs skaičiavimai)."""
from datetime import date

from fastapi import APIRouter

from ..cache import cached
from ..db import ch

router = APIRouter(prefix="/reports", tags=["reports"])
TTL = 600


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


# TODO (3 sav.): /escape-rate, /hints, /funnel (windowFunnel), /retention, /searches
