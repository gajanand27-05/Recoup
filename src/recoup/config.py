import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # default_factory, not a bare os.getenv() call: a plain default is evaluated
    # once at import, which makes the values impossible to override in a test and
    # freezes whatever the environment happened to be when the module first loaded.
    rzp_key_id: str = field(default_factory=lambda: _env("RZP_KEY_ID"))
    rzp_key_secret: str = field(default_factory=lambda: _env("RZP_KEY_SECRET"))
    rzp_webhook_secret: str = field(default_factory=lambda: _env("RZP_WEBHOOK_SECRET"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    experiment_salt: str = field(default_factory=lambda: _env("EXPERIMENT_SALT", "recoup-2026-08"))
    db_path: str = field(default_factory=lambda: _env("RECOUP_DB", "runs/recoup.db"))


settings = Settings()
