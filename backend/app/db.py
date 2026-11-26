"""Prisijungimai prie visų keturių duomenų bazių (vienas modulis – lengva importuoti)."""
from functools import lru_cache

import clickhouse_connect
import redis
import redis.asyncio as aioredis
from elasticsearch import Elasticsearch
from pymongo import MongoClient

from .config import settings

# MongoDB – pagrindiniai (operaciniai) duomenys
mongo_client = MongoClient(settings.mongo_url, tz_aware=False)
db = mongo_client[settings.mongo_db]

# Redis – cache, sesijos, užraktai, rekordų lentelės (ZSET), Pub/Sub
r = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def async_redis() -> aioredis.Redis:
    """Asinchroninis Redis klientas WebSocket'ui (atskiras kiekvienam ryšiui)."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)

# ElasticSearch – pilno teksto paieška
es = Elasticsearch(settings.es_url)

ROOMS_INDEX = "rooms"



@lru_cache
def ch():
    """ClickHouse klientas (kuriamas tingiai – kai serveris jau pasileidęs)."""
    return clickhouse_connect.get_client(
        host=settings.ch_host, port=settings.ch_port,
        username=settings.ch_user, password=settings.ch_password,
        database=settings.ch_db,
        autogenerate_session_id=False,  # leidžia lygiagrečias užklausas iš kelių gijų
    )
