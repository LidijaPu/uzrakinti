from fastapi import APIRouter

from ..db import ch, db, es, r

router = APIRouter(tags=["health"])


@router.get("/health", summary="Patikrina ryšį su visomis 4 duomenų bazėmis")
def health():
    status = {}
    for name, check in {
        "mongo": lambda: db.command("ping")["ok"] == 1,
        "redis": lambda: r.ping(),
        "elasticsearch": lambda: es.ping(),
        "clickhouse": lambda: ch().command("SELECT 1") == 1,
    }.items():
        try:
            status[name] = "ok" if check() else "fail"
        except Exception as e:  # noqa: BLE001
            status[name] = f"fail: {e}"
    return status
