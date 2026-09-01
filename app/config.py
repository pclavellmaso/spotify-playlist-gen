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
    ai_provider: str
    ai_model: str
    ai_api_key: str
    ai_base_url: str
    lastfm_api_key: str
    db_path: Path
    host: str
    port: int

    @property
    def token_path(self) -> Path:
        return self.db_path.parent / "token.json"


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else ROOT / path


# Modelos por defecto de cada proveedor, para no obligar a saberselos.
MODELOS_POR_DEFECTO = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-4.1-mini",
    "ollama": "llama3.1",
    "lmstudio": "local-model",
    "openrouter": "anthropic/claude-sonnet-4.5",
    "groq": "llama-3.3-70b-versatile",
}


def _ia() -> dict[str, str]:
    """Configuracion del modelo, con las variables antiguas como respaldo.

    Un .env escrito antes de que existiera el soporte para otros proveedores
    sigue funcionando sin tocar nada.
    """
    proveedor = os.getenv("AI_PROVIDER", "anthropic").lower().strip()
    return {
        "ai_provider": proveedor,
        "ai_model": (
            os.getenv("AI_MODEL")
            or os.getenv("ANTHROPIC_MODEL")
            or MODELOS_POR_DEFECTO.get(proveedor, "")
        ),
        "ai_api_key": (
            os.getenv("AI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY", "")
            or os.getenv("OPENAI_API_KEY", "")
        ),
        "ai_base_url": os.getenv("AI_BASE_URL", ""),
    }


def load_settings() -> Settings:
    db_path = _resolve(os.getenv("DB_PATH", "data/library.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
        spotify_redirect_uri=os.getenv(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/callback"
        ),
        **_ia(),
        lastfm_api_key=os.getenv("LASTFM_API_KEY", ""),
        db_path=db_path,
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8000")),
    )


settings = load_settings()


ENV_PATH = ROOT / ".env"


def write_env(valores: dict[str, str]) -> None:
    """Actualiza .env conservando comentarios, orden y claves no tocadas.

    Se escribe con permisos 0600 porque el fichero contiene credenciales. Los
    valores nunca se registran en el log.
    """
    pendientes = dict(valores)
    lineas: list[str] = []

    if ENV_PATH.exists():
        for linea in ENV_PATH.read_text().splitlines():
            desnuda = linea.strip()
            if desnuda and not desnuda.startswith("#") and "=" in desnuda:
                clave = desnuda.split("=", 1)[0].strip()
                if clave in pendientes:
                    lineas.append(f"{clave}={pendientes.pop(clave)}")
                    continue
            lineas.append(linea)

    # Lo que no existia en el fichero se anade al final.
    for clave, valor in pendientes.items():
        lineas.append(f"{clave}={valor}")

    ENV_PATH.write_text("\n".join(lineas).rstrip() + "\n")
    ENV_PATH.chmod(0o600)
