"""Duomenų bazių struktūros sukūrimas. Idempotentiška – galima leisti daug kartų.

MongoDB: kolekcijos su $jsonSchema validatoriais + indeksai
ElasticSearch: indeksas `rooms` su lietuvišku analizatoriumi
ClickHouse: lentelė `events`
"""
import logging
import time

from pymongo import ASCENDING, DESCENDING, GEOSPHERE, IndexModel
from pymongo.errors import CollectionInvalid

from .db import ROOMS_INDEX, ch, db, es

log = logging.getLogger("init_db")

# ---------------------------------------------------------------- MongoDB
OID = {"bsonType": "objectId"}
DATE = {"bsonType": "date"}
STR = {"bsonType": "string"}
INT = {"bsonType": "int"}
NUM = {"bsonType": ["double", "int", "decimal"]}

VALIDATORS: dict[str, dict] = {
    "users": {
        "bsonType": "object",
        "required": ["type", "email", "passwordHash", "firstName", "lastName", "createdAt"],
        "properties": {
            "type": {"enum": ["player", "gameMaster", "manager", "admin"]},
            "email": {"bsonType": "string", "pattern": "^.+@.+$"},
            "passwordHash": STR, "firstName": STR, "lastName": STR,
            "birthYear": {"bsonType": "int", "minimum": 1900, "maximum": 2030},
            "achievements": {"bsonType": "array"},
            "stats": {"bsonType": "object"},
            "createdAt": DATE,
        },
    },
    "locations": {
        "bsonType": "object",
        "required": ["name", "city", "address", "geo"],
        "properties": {"name": STR, "city": STR, "address": STR, "geo": {"bsonType": "object"}},
    },
    "rooms": {
        "bsonType": "object",
        "required": ["locationId", "slug", "name", "theme", "difficulty", "minPlayers",
                     "maxPlayers", "durationMin", "pricePerPlayer", "slotTimes", "isActive"],
        "properties": {
            "locationId": OID, "slug": STR, "name": STR, "theme": STR, "description": STR,
            "difficulty": {"bsonType": "int", "minimum": 1, "maximum": 5},
            "minPlayers": {"bsonType": "int", "minimum": 1},
            "maxPlayers": {"bsonType": "int", "maximum": 12},
            "durationMin": INT, "ageLimit": INT, "pricePerPlayer": NUM,
            "tags": {"bsonType": "array", "items": STR},
            "slotTimes": {"bsonType": "array", "items": {"bsonType": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"}},
            "hints": {"bsonType": "array", "items": {
                "bsonType": "object", "required": ["hintId", "order", "text"],
                "properties": {"hintId": STR, "order": INT, "text": STR, "penaltySec": INT}}},
            "rating": {"bsonType": "object"},
            "isActive": {"bsonType": "bool"},
        },
    },
    "teams": {
        "bsonType": "object",
        "required": ["name", "captainId", "members", "createdAt"],
        "properties": {
            "name": STR, "captainId": OID, "createdAt": DATE,
            "members": {"bsonType": "array", "maxItems": 10, "items": {
                "bsonType": "object", "required": ["userId", "role"],
                "properties": {"userId": OID, "role": {"enum": ["captain", "member"]}, "joinedAt": DATE}}},
        },
    },
    "team_invitations": {
        "bsonType": "object",
        "required": ["teamId", "userId", "status", "createdAt"],
        "properties": {"teamId": OID, "userId": OID, "createdAt": DATE,
                       "status": {"enum": ["pending", "accepted", "declined"]}},
    },
    "bookings": {
        "bsonType": "object",
        "required": ["roomId", "locationId", "bookedBy", "startAt", "endAt",
                     "playersCount", "status", "active", "totalPrice", "createdAt"],
        "properties": {
            "roomId": OID, "locationId": OID, "teamId": {"bsonType": ["objectId", "null"]},
            "bookedBy": OID, "startAt": DATE, "endAt": DATE,
            "playersCount": {"bsonType": "int", "minimum": 1},
            "status": {"enum": ["confirmed", "completed", "cancelled", "noShow"]},
            "active": {"bsonType": "bool"},
            "totalPrice": NUM, "promoCode": {"bsonType": ["string", "null"]},
            "payment": {"bsonType": "object"}, "createdAt": DATE,
        },
    },
    "game_sessions": {
        "bsonType": "object",
        "required": ["bookingId", "roomId", "gameMasterId", "startedAt"],
        "properties": {
            "bookingId": OID, "roomId": OID, "teamId": {"bsonType": ["objectId", "null"]},
            "gameMasterId": OID, "startedAt": DATE, "finishedAt": DATE,
            "escaped": {"bsonType": "bool"}, "timeSec": INT, "penaltySec": INT, "finalTimeSec": INT,
            "hintsUsed": {"bsonType": "array"},
        },
    },
    "reviews": {
        "bsonType": "object",
        "required": ["roomId", "bookingId", "userId", "rating", "createdAt"],
        "properties": {"roomId": OID, "bookingId": OID, "userId": OID, "text": STR, "createdAt": DATE,
                       "rating": {"bsonType": "int", "minimum": 1, "maximum": 5}},
    },
    "staff_shifts": {
        "bsonType": "object",
        "required": ["staffId", "locationId", "from", "to"],
        "properties": {"staffId": OID, "locationId": OID, "from": DATE, "to": DATE},
    },
    "vouchers": {
        "bsonType": "object",
        "required": ["code", "value", "remaining", "expiresAt"],
        "properties": {"code": STR, "value": NUM, "expiresAt": DATE, "purchasedBy": OID,
                       "remaining": {"bsonType": ["double", "int", "decimal"], "minimum": 0}},
    },
    "promo_codes": {
        "bsonType": "object",
        "required": ["code", "discountPct", "validFrom", "validTo", "maxUses", "usedCount"],
        "properties": {"code": STR, "validFrom": DATE, "validTo": DATE, "maxUses": INT,
                       "discountPct": {"bsonType": "int", "minimum": 1, "maximum": 100},
                       "usedCount": {"bsonType": "int", "minimum": 0}},
    },
}

INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("email", ASCENDING)], unique=True)],
    "locations": [IndexModel([("geo", GEOSPHERE)]), IndexModel([("city", ASCENDING)])],
    "rooms": [
        IndexModel([("slug", ASCENDING)], unique=True),
        IndexModel([("locationId", ASCENDING), ("isActive", ASCENDING)]),
    ],
    "teams": [
        IndexModel([("name", ASCENDING)], unique=True),
        IndexModel([("members.userId", ASCENDING)]),  # multikey
    ],
    "team_invitations": [
        IndexModel([("teamId", ASCENDING), ("userId", ASCENDING)], unique=True,
                   partialFilterExpression={"status": "pending"}, name="uniq_pending_invite"),
    ],
    "bookings": [
        # PAGRINDINĖ GARANTIJA: vienas aktyvus užsakymas tam pačiam kambariui ir laikui
        IndexModel([("roomId", ASCENDING), ("startAt", ASCENDING)], unique=True,
                   partialFilterExpression={"active": True}, name="uniq_active_slot"),
        IndexModel([("bookedBy", ASCENDING), ("startAt", DESCENDING)]),
        IndexModel([("locationId", ASCENDING), ("startAt", ASCENDING)]),
    ],
    "game_sessions": [
        IndexModel([("bookingId", ASCENDING)], unique=True),
        IndexModel([("roomId", ASCENDING), ("escaped", ASCENDING), ("finalTimeSec", ASCENDING)]),
    ],
    "reviews": [
        IndexModel([("bookingId", ASCENDING), ("userId", ASCENDING)], unique=True),
        IndexModel([("roomId", ASCENDING), ("createdAt", DESCENDING)]),
    ],
    "staff_shifts": [IndexModel([("locationId", ASCENDING), ("from", ASCENDING)])],
    "vouchers": [IndexModel([("code", ASCENDING)], unique=True)],
    "promo_codes": [IndexModel([("code", ASCENDING)], unique=True)],
}


def init_mongo() -> None:
    for name, schema in VALIDATORS.items():
        try:
            db.create_collection(name, validator={"$jsonSchema": schema})
        except CollectionInvalid:  # jau egzistuoja → atnaujinam validatorių
            db.command("collMod", name, validator={"$jsonSchema": schema})
        if INDEXES.get(name):
            db[name].create_indexes(INDEXES[name])
    log.info("MongoDB paruošta")


# ---------------------------------------------------------------- ElasticSearch
ROOMS_MAPPING = {
    "properties": {
        "name": {"type": "text", "analyzer": "lithuanian",
                 "fields": {"suggest": {"type": "search_as_you_type"}}},
        "description": {"type": "text", "analyzer": "lithuanian"},
        "slug": {"type": "keyword"},
        "theme": {"type": "keyword"},
        # text, kad paieška su klaida rastų žymas; .raw – tiksliam filtrui
        "tags": {"type": "text", "analyzer": "lithuanian", "fields": {"raw": {"type": "keyword"}}},
        "city": {"type": "keyword"},
        "locationName": {"type": "keyword"},
        "difficulty": {"type": "integer"},
        "minPlayers": {"type": "integer"},
        "maxPlayers": {"type": "integer"},
        "durationMin": {"type": "integer"},
        "price": {"type": "float"},
        "rating": {"type": "float"},
        "location": {"type": "geo_point"},
        "isActive": {"type": "boolean"},
    }
}


def init_es() -> None:
    if not es.indices.exists(index=ROOMS_INDEX):
        es.indices.create(index=ROOMS_INDEX, mappings=ROOMS_MAPPING)
    log.info("ElasticSearch paruošta")


# ---------------------------------------------------------------- ClickHouse
EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
    ts          DateTime,
    eventType   LowCardinality(String),
    userId      String,
    roomId      String,
    locationId  String,
    bookingId   String,
    sessionId   String,
    value       Float64,
    meta        String
) ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (eventType, locationId, ts)
"""


def init_clickhouse() -> None:
    ch().command(EVENTS_DDL)
    log.info("ClickHouse paruošta")


def init_all(retries: int = 30, delay: float = 2.0) -> None:
    """Bandoma kelis kartus – ElasticSearch ir ClickHouse gali startuoti lėčiau."""
    for attempt in range(1, retries + 1):
        try:
            init_mongo()
            init_es()
            init_clickhouse()
            return
        except Exception as e:  # noqa: BLE001
            log.warning("DB dar neparuoštos (%s/%s): %s", attempt, retries, e)
            ch.cache_clear()
            time.sleep(delay)
    raise RuntimeError("Nepavyko inicializuoti duomenų bazių")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_all()
