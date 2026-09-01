"""Acceso al modelo de lenguaje, aislado del resto del proyecto.

El perfilado necesita dos cosas de un modelo: que devuelva JSON conforme a un
esquema y que sus errores se puedan clasificar en «esto no va a mejorar
reintentando» y «esto ha sido mala suerte». Nada más. Con esa superficie tan
estrecha, cambiar de proveedor es enchufar otra implementacion.

Hay dos:

- `AnthropicModel`, que usa el SDK oficial y el cacheo de prefijo del prompt,
  que es lo que abarata un barrido de miles de canciones.
- `OpenAIModel`, que habla el dialecto `/chat/completions` por HTTP directo.
  Eso cubre OpenAI, OpenRouter, Groq, LM Studio y **Ollama**, y ese ultimo
  caso importa: con un modelo local el proyecto deja de costar dinero.

No se anade ninguna dependencia para la segunda: se usa el mismo httpx2 que ya
usan Spotify y Last.fm.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol, TypeVar

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Fallo del modelo, ya clasificado.

    `permanent` distingue lo que no mejora reintentando -sin saldo, clave
    invalida, modelo inexistente, peticion mal formada- de lo transitorio.
    `human` es el texto que acaba en la pantalla del usuario.
    """

    def __init__(self, human: str, permanent: bool, causa: Exception | None = None):
        super().__init__(human)
        self.human = human
        self.permanent = permanent
        self.causa = causa


class Modelo(Protocol):
    nombre: str

    def parse(self, system: str, user: str, esquema: type[T], max_tokens: int) -> T | None:
        """Devuelve una instancia del esquema, o None si la respuesta es ilegible."""


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------
class AnthropicModel:
    def __init__(self, modelo: str, api_key: str = "", cliente: Any = None):
        import anthropic

        self._anthropic = anthropic
        self.nombre = modelo
        self.client = cliente or (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )

    def parse(self, system: str, user: str, esquema: type[T], max_tokens: int) -> T | None:
        try:
            respuesta = self.client.messages.parse(
                model=self.nombre,
                max_tokens=max_tokens,
                # El prefijo estable se cachea entre lotes: es lo que abarata
                # perfilar miles de canciones.
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_format=esquema,
            )
        except Exception as exc:
            raise self._traducir(exc) from exc
        return respuesta.parsed_output

    def _traducir(self, exc: Exception) -> LLMError:
        a = self._anthropic
        texto = str(exc)
        permanentes = (
            a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError,
            a.BadRequestError, a.UnprocessableEntityError,
        )
        if "credit balance is too low" in texto:
            return LLMError(
                "La cuenta de Anthropic no tiene saldo. Anade creditos en "
                "console.anthropic.com (Plans & Billing) y vuelve a intentarlo.",
                permanent=True, causa=exc,
            )
        if isinstance(exc, a.AuthenticationError):
            return LLMError("La clave del modelo no es valida. Revisala en .env.",
                            permanent=True, causa=exc)
        if isinstance(exc, a.PermissionDeniedError):
            return LLMError(f"La clave no tiene acceso al modelo '{self.nombre}'.",
                            permanent=True, causa=exc)
        if isinstance(exc, a.NotFoundError):
            return LLMError(f"El modelo '{self.nombre}' no existe. Revisa AI_MODEL en .env.",
                            permanent=True, causa=exc)
        if isinstance(exc, a.RateLimitError):
            return LLMError("El proveedor esta limitando las peticiones. Prueba en unos minutos.",
                            permanent=False, causa=exc)
        if isinstance(exc, permanentes):
            return LLMError(f"Peticion rechazada por el proveedor: {texto}",
                            permanent=True, causa=exc)
        if isinstance(exc, a.APIError):
            return LLMError(f"Error temporal del proveedor: {texto}", permanent=False, causa=exc)
        raise exc


# --------------------------------------------------------------------------
# Dialecto OpenAI: OpenAI, OpenRouter, Groq, LM Studio, Ollama…
# --------------------------------------------------------------------------
class OpenAIModel:
    def __init__(self, modelo: str, base_url: str, api_key: str = ""):
        self.nombre = modelo
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # Los servidores locales suelen no admitir `json_schema`. En cuanto uno
        # lo rechaza se recuerda y se pasa a pedir JSON a secas con el esquema
        # descrito en el prompt, que entienden todos.
        self._json_schema = True

    def parse(self, system: str, user: str, esquema: type[T], max_tokens: int) -> T | None:
        esquema_json = esquema.model_json_schema()
        crudo = self._llamar(system, user, esquema, esquema_json, max_tokens)
        if crudo is None:
            return None
        try:
            return esquema.model_validate_json(crudo)
        except ValidationError as exc:
            log.warning("El modelo devolvio JSON que no encaja con el esquema: %s", exc)
            return None
        except json.JSONDecodeError:
            log.warning("El modelo no devolvio JSON")
            return None

    def _llamar(self, system: str, user: str, esquema: type[T],
                esquema_json: dict, max_tokens: int) -> str | None:
        cuerpo: dict[str, Any] = {
            "model": self.nombre,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": self._system(system, esquema_json)},
                {"role": "user", "content": user},
            ],
        }
        if self._json_schema:
            cuerpo["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": esquema.__name__, "schema": esquema_json},
            }
        else:
            cuerpo["response_format"] = {"type": "json_object"}

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                json=cuerpo,
                # Un modelo local tarda minutos por lote, y es legitimo: no hay
                # cola ni red, solo una GPU pequena haciendo el trabajo.
                timeout=900.0,
            )
        except httpx.HTTPError as exc:
            raise LLMError(
                f"No se pudo contactar con el modelo en {self.base_url}. "
                "Si es un servidor local, comprueba que este arrancado.",
                permanent=False, causa=exc,
            ) from exc

        if resp.status_code == 400 and self._json_schema and "response_format" in resp.text:
            # Servidor que no entiende json_schema: se reintenta una vez en el
            # modo compatible y se recuerda para el resto del barrido.
            log.info("El proveedor no admite json_schema; se pasa a json_object")
            self._json_schema = False
            return self._llamar(system, user, esquema, esquema_json, max_tokens)

        if resp.status_code != 200:
            raise self._traducir(resp)

        try:
            datos = resp.json()
            return datos["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError(f"Respuesta inesperada del proveedor: {resp.text[:200]}",
                           permanent=False, causa=exc) from exc

    def _system(self, system: str, esquema_json: dict) -> str:
        if self._json_schema:
            return system
        return (
            f"{system}\n\nResponde unicamente con un objeto JSON que cumpla este "
            f"esquema, sin texto alrededor ni bloques de codigo:\n"
            f"{json.dumps(esquema_json, ensure_ascii=False)}"
        )

    def _traducir(self, resp: Any) -> LLMError:
        texto = (resp.text or "")[:300]
        bajo = texto.lower()
        if resp.status_code in (401, 403):
            return LLMError("La clave del modelo no es valida o no tiene acceso. Revisala en .env.",
                            permanent=True)
        if resp.status_code == 404:
            return LLMError(
                f"El proveedor no encuentra el modelo '{self.nombre}' en {self.base_url}.",
                permanent=True)
        if resp.status_code == 429:
            return LLMError("El proveedor esta limitando las peticiones. Prueba en unos minutos.",
                            permanent=False)
        if resp.status_code == 402 or "quota" in bajo or "insufficient" in bajo or "billing" in bajo:
            return LLMError("La cuenta del proveedor no tiene saldo.", permanent=True)
        if resp.status_code >= 500:
            return LLMError(f"El proveedor devolvio un error temporal ({resp.status_code}).",
                            permanent=False)
        return LLMError(f"Peticion rechazada por el proveedor ({resp.status_code}): {texto}",
                        permanent=True)


# --------------------------------------------------------------------------
PRESETS = {
    # base_url por defecto para los dialectos OpenAI mas habituales.
    "openai": "https://api.openai.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def build_model(proveedor: str, modelo: str, api_key: str = "", base_url: str = "") -> Modelo:
    """Crea el cliente del proveedor pedido."""
    proveedor = (proveedor or "anthropic").lower().strip()
    if proveedor == "anthropic":
        return AnthropicModel(modelo, api_key)
    if proveedor in PRESETS or base_url:
        return OpenAIModel(modelo, base_url or PRESETS[proveedor], api_key)
    raise LLMError(
        f"Proveedor '{proveedor}' desconocido. Usa uno de: anthropic, "
        f"{', '.join(PRESETS)}; o indica AI_BASE_URL.",
        permanent=True,
    )
