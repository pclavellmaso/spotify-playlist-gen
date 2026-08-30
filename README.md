# Playlists por momento

Describe un momento en lenguaje natural — *"momento calma en la piscina haciendo
cervecita"* — y la app saca de **tu propia biblioteca de Spotify** las canciones que
encajan, las ordena y te las guarda como playlist nueva.

No recomienda música que no conoces: filtra la que ya te gusta.

## Por qué está construido así

Spotify **retiró el endpoint `audio-features`** (energy, valence, danceability…) el
27 de noviembre de 2024 para toda app nueva, junto a `audio-analysis`,
`recommendations` y `related-artists`. El enfoque clásico —pedir el vector acústico
de cada canción y filtrar por umbrales— ya no es posible.

Aquí el perfil de cada canción lo infiere **Claude** a partir de sus metadatos
(artista, título, álbum, año). Es una estimación, no una medición, así que cada
etiqueta lleva un `confidence`: cuando el modelo no reconoce una canción, su perfil
se arrastra hacia neutro en vez de decidir por sí solo.

El resto es deliberadamente aburrido y determinista: emparejar es una distancia
ponderada sobre siete ejes fijos, sin LLM y con tests.

## Cómo funciona

```
Spotify  ──sync──▶  SQLite  ──Claude (una vez por canción)──▶  perfil de vibe
                                                                     │
tu frase ──Claude──▶ perfil objetivo ──distancia ponderada──▶ selección ──▶ playlist
```

El etiquetado se cachea de forma permanente: pagas por canción **una sola vez**, y
las consultas posteriores no llaman al modelo salvo para interpretar tu frase.

Cada canción se proyecta en siete ejes 0-100 (`energy`, `valence`, `danceability`,
`acousticness`, `tempo_feel`, `vocal_focus`, `warmth`), un vocabulario cerrado de 15
contextos (`piscina_verano`, `after_hours`, `concentracion_trabajo`…) y hasta seis
adjetivos libres. Tu frase se traduce al mismo espacio, y sólo entonces se comparan.

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y rellena las dos claves
python run.py             # http://127.0.0.1:8000
```

**Spotify** — crea una app en [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard),
copia el Client ID (no hace falta el secret: se usa PKCE) y añade como Redirect URI
exactamente `http://127.0.0.1:8000/api/auth/callback`. Spotify ya no acepta
`localhost`, tiene que ser la IP de loopback.

**Anthropic** — una API key de [console.anthropic.com](https://console.anthropic.com).

En la web: *Sincronizar* → *Analizar pendientes* (tarda; puedes cerrar y volver) →
escribe el momento → *Generar* → *Guardar en Spotify*.

## Límites que conviene conocer antes de invertir tiempo

- **Developer Mode sólo admite 5 usuarios de prueba** desde marzo de 2026 (antes 25),
  y ahora exige que el desarrollador tenga cuenta Premium. Salir de ahí requiere
  *extended quota*: empresa registrada y 250.000 usuarios activos mensuales. Como
  producto público esto **no es viable hoy**; como herramienta personal, perfecta.
- El perfil sonoro es una inferencia. Con música muy nicho o muy nueva el modelo
  bajará el `confidence`, y debe hacerlo: es la señal de que no la conoce.
- Todo corre en local. El token de Spotify se guarda en `data/token.json` con
  permisos `0600` y no sale de tu máquina.

## Coste

Sólo se etiqueta cada canción una vez, en lotes de 40 con el prefijo del prompt
cacheado. Por defecto usa `claude-opus-5`; si vas a analizar miles de canciones,
`ANTHROPIC_MODEL=claude-haiku-4-5` abarata mucho el barrido inicial a cambio de algo
de precisión en el catálogo menos conocido. Interpretar cada frase es una llamada
suelta y corta.

## Ajustes útiles

| Parámetro | Qué hace |
|---|---|
| **Nota mínima** | Sube a 70 para una selección corta y muy fiel; baja a 40 si sale vacía |
| **Máx. por artista** | Evita que un disco cope la playlist entera |
| `order: flow` | Ordena por energía ascendente (curva de escucha) en vez de por afinidad |

Tocar los ejes o los contextos en `app/vibes.py` invalida las etiquetas guardadas:
sube `TAGGER_VERSION` y se re-etiquetará sólo lo necesario.

## Tests

```bash
python -m pytest tests/ -q
```

18 tests sobre el scorer, la capa SQLite y el recorrido HTTP completo. Ninguno
llama a la API de Spotify ni a la de Claude.

## Estructura

| Fichero | Responsabilidad |
|---|---|
| `app/vibes.py` | Vocabulario y esquemas Pydantic compartidos |
| `app/spotify.py` | OAuth PKCE, paginación, rate limiting, creación de playlists |
| `app/db.py` | Cache SQLite de biblioteca y etiquetas |
| `app/tagger.py` | Las dos llamadas a Claude: etiquetar y traducir la petición |
| `app/matcher.py` | Puntuación y selección (sin LLM) |
| `app/main.py` | API FastAPI |
