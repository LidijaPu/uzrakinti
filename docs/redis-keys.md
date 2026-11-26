# Redis raktų schema

| Raktas | Tipas | TTL | Paskirtis | Kur kode |
|---|---|---|---|---|
| `session:{token}` | STRING (JSON) | 24 h, slenkantis | prisijungę vartotojai | `routers/auth.py`, `deps.py` |
| `rate:login:{ip}` | STRING (INCR) | 60 s | prisijungimo bandymų ribojimas | `routers/auth.py` |
| `hold:{roomId}:{startAt}` | STRING, `SET NX` | 10 min. | laikinas laiko užlaikymas mokant | `routers/bookings.py` |
| `cache:availability:{roomId}:{date}` | STRING (JSON) | 60 s | užimti laikai; invaliduojama rezervuojant/atšaukiant | `routers/rooms.py` |
| `cache:room:{slug}` | STRING (JSON) | 10 min. | kambario puslapis | `routers/rooms.py` |
| `cache:report:{name}:{params}` | STRING (JSON) | 10 min. | ClickHouse ataskaitos | `routers/reports.py` |
| `lb:room:{roomId}` | ZSET (score = laikas s) | – | kambario rekordai | `routers/leaderboards.py` |
| `lb:month:{yyyymm}` | ZSET | – | mėnesio TOP | `routers/leaderboards.py` |
| `lb:nohints` | ZSET | – | „be užuominų“ lyga | `routers/leaderboards.py` |
| `game:{sessionId}` | HASH | 3 h | gyva žaidimo būsena (startas, užuominos, bauda) | `routers/games.py` |
| `game:{sessionId}:hints` | SET (`SADD`) | 3 h | išsiųstos užuominos – ta pati nesiunčiama dukart | `routers/games.py` |
| `room:{roomId}:game` | STRING | 3 h | kuris žaidimas dabar vyksta kambaryje | `routers/games.py` |
| `room:{roomId}:screen` | Pub/Sub kanalas | – | įvykiai į kambario ekraną (WebSocket `/ws/rooms/{roomId}`) | `routers/games.py` |
