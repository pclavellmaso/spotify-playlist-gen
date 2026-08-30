"""Configuracion cargada desde el entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

# Permisos minimos: leer likes/playlists y escribir playlists nuevas.
SCOPES = (
    "user-library-read "
    "playlist-read-private "
    "playlist-modify-private "
    "playlist-modify-public"
)


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    spotify_redirect_uri: str
    anthropic_model: str
    db_path: Path
    host: str
    port: int

    @property
    def token_path(self) -> Path:
        return self.db_path.parent / "token.json"


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else ROOT / path


def load_settings() -> Settings:
    db_path = _resolve(os.getenv("DB_PATH", "data/library.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
        spotify_redirect_uri=os.getenv(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/callback"
        ),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5"),
        db_path=db_path,
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8000")),
    )


settings = load_settings()
