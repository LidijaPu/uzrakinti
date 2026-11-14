from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigūracija iš aplinkos kintamųjų (.env). Pavadinimai nejautrūs raidžių dydžiui."""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017/?directConnection=true"
    mongo_db: str = "uzrakinti"
    redis_url: str = "redis://localhost:6379/0"
    es_url: str = "http://localhost:9200"
    ch_host: str = "localhost"
    ch_port: int = 8123
    ch_user: str = "app"
    ch_password: str = "app"
    ch_db: str = "uzrakinti"
    session_ttl: int = 86400   # 24 h
    hold_ttl: int = 600        # 10 min. laiko užlaikymas


settings = Settings()
