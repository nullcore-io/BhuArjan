from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://bhuarjan:bhuarjan_dev@localhost:5433/bhuarjan"
    MINIO_ENDPOINT: str = "localhost:9100"
    MINIO_ACCESS_KEY: str = "bhuarjan"
    MINIO_SECRET_KEY: str = "bhuarjan_dev"
    MINIO_SECURE: bool = False
    MINIO_PUBLIC_ENDPOINT: str = "localhost:9100"
    MINIO_BUCKET: str = "bhuarjan-docs"
    JWT_SECRET: str = "dev-secret-change-me"
    # AES-256-GCM key for field-level PII encryption, 64 hex characters
    # (Docs/rules.md C5, Docs/Backend.md §10). Empty is only tolerated in DEMO_MODE,
    # where app.core.crypto falls back to a published development constant; outside
    # DEMO_MODE the API refuses to start without a real key.
    PII_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    DEMO_MODE: bool = True
    SEED_ON_START: bool = False
    RULESETS_DIR: str = "rulesets"
    LLM_EXTRACTION_URL: str = ""  # empty → regex-only extraction (offline demo)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
