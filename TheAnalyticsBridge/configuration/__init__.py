import os
from pathlib import Path

from dotenv import load_dotenv


ENV_FILES = {
    "development": ".env",
    "dev": ".env",
    "production": ".env-prod",
    "prod": ".env-prod",
}


def load_environment() -> Path:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    if environment not in ENV_FILES:
        raise ValueError("APP_ENV must be development, dev, production, or prod")
    bridge_path = Path(__file__).resolve().parent.parent
    load_dotenv(dotenv_path=bridge_path / ENV_FILES[environment], override=False)
    return bridge_path