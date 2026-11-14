"""Įvykių rašymas į ClickHouse (analitikai). Klaida analitikoje neturi sugadinti pagrindinio veiksmo."""
import json
import logging
from datetime import datetime, timezone

from .db import ch

log = logging.getLogger("events")

COLUMNS = ["ts", "eventType", "userId", "roomId", "locationId",
           "bookingId", "sessionId", "value", "meta"]


def log_event(event_type: str, *, user_id: str = "", room_id: str = "", location_id: str = "",
              booking_id: str = "", session_id: str = "", value: float = 0.0,
              meta: dict | None = None, ts: datetime | None = None) -> None:
    row = [ts or datetime.now(timezone.utc).replace(tzinfo=None), event_type, user_id, room_id,
           location_id, booking_id, session_id, float(value), json.dumps(meta or {}, default=str)]
    try:
        ch().insert("events", [row], column_names=COLUMNS)
    except Exception as e:  # noqa: BLE001
        log.warning("Nepavyko įrašyti įvykio %s: %s", event_type, e)
