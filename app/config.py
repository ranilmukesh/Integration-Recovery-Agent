import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "local")
    ALLOW_SQLITE_FALLBACK: bool = os.getenv("ALLOW_SQLITE_FALLBACK", "true").lower() in ("true", "1", "yes")
    NEON_DB_URL: str = os.getenv(
        "NEON_DB_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/integration_recovery_demo"
    )
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    PORT: int = int(os.getenv("PORT", "7860"))


settings = Settings()
