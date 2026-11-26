import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .init_db import init_all
from .routers import (admin, auth, bookings, games, health, leaderboards, me, promo, reports,
                      reviews, rooms, search, teams)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_all()  # sukuria kolekcijas, indeksus, ES indeksą, ClickHouse lentelę
    yield


app = FastAPI(
    title="Užrakinti – escape room tinklo API",
    description="MongoDB + Redis + ElasticSearch + ClickHouse. Dokumentacija: /docs ir /redoc.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev serveris
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (health.router, auth.router, me.router, rooms.router, reviews.router, bookings.router,
               promo.router, teams.router, games.router, search.router, leaderboards.router,
               reports.router, admin.router):
    app.include_router(router)
