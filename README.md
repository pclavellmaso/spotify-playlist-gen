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
(artista, título, álbum, año) y de los **tags de comunidad de Last.fm**. Es una
estimación, no una medición, así que cada etiqueta lleva un `confidence`: cuando el
modelo no reconoce una canción, su perfil se arrastra hacia neutro en vez de decidir
por sí solo.

El resto es deliberadamente aburrido y determinista: emparejar es una distancia
ponderada sobre siete ejes fijos, sin LLM y con tests.

## Cómo funciona

```
Spotify ──sync──▶ SQLite ──┬── Last.fm (álbum + artista) ──┐
                           │                               ▼
                           └──────────── Claude (una vez por canción) ──▶ perfil
                                                                            │
tu frase ──Claude──▶ perfil objetivo ──distancia ponderada──▶ selección ──▶ playlist
```

El etiquetado se cachea de forma permanente: pagas por canción **una sola vez**, y
las consultas posteriores no llaman al modelo salvo para interpretar tu frase.

Cada canción se proyecta en siete ejes 0-100 (`energy`, `valence`, `danceability`,
`acousticness`, `tempo_feel`, `vocal_focus`, `warmth`), un vocabulario cerrado de 15
contextos (`piscina_verano`, `after_hours`, `concentracion_trabajo`…) y hasta seis
adjetivos libres. Tu frase se traduce al mismo espacio, y sólo entonces se comparan.

### El papel de Last.fm

Last.fm no mide nada acústico, pero sus tags los escriben personas que sí han
escuchado la música. Sirven para lo que el modelo no puede saber: que Teddy Killerz
es `drum and bass, neurofunk`, que Folamour es `house, french house, deep house`.

Se consultan **álbum y artista, no la canción**: `track.getTopTags` devuelve vacío de
forma sistemática, incluso para temas con cientos de miles de oyentes. La
contrapartida es que dos canciones del mismo disco reciben los mismos tags, así que
sitúan el género y la época pero no distinguen una balada de un corte bailable; al
prompt se le dice explícitamente.

Es opcional. Sin `LASTFM_API_KEY` la app funciona igual, sólo que peor en catálogo
poco conocido.

## Puesta en marcha

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env      # y rellena las claves
./.venv/bin/python run.py # http://127.0.0.1:8000
```

Sirve cualquier Python 3.10+; se usa `uv` porque en macOS 26 el `python@3.13` de
Homebrew viene con el `pyexpat` roto y no deja crear venvs.

**Spotify** — crea una app en [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard),
marca *Web API*, copia el Client ID (no hace falta el secret: se usa PKCE) y añade
como Redirect URI exactamente `http://127.0.0.1:8000/api/auth/callback`. Spotify ya
no acepta `localhost`, tiene que ser la IP de loopback.

**Anthropic** — una API key de [console.anthropic.com](https://console.anthropic.com),
con saldo en *Plans & Billing*.

**Last.fm** *(opcional)* — key gratuita en
[last.fm/api/account/create](https://www.last.fm/api/account/create). Los campos de
callback y homepage pueden ir vacíos.

En la web: *Sincronizar* → *Analizar pendientes* (tarda; puedes cerrar y volver) →
escribe el momento → *Generar* → *Guardar en Spotify*.

*Analizar* sólo etiqueta en local y *Generar* sólo enseña la selección: la playlist
se crea únicamente al pulsar *Guardar en Spotify*.

## Qué tal funciona

Medido sobre 90 canciones de una biblioteca real, dominada por house, DnB y
electrónica reciente de sello pequeño:

| | sin Last.fm | con Last.fm |
|---|---|---|
| `confidence` medio | 32.0 | **44.6** |
| canciones por debajo de 40 | 71% | **27%** |
| dispersión de `danceability` | 9.0 | **12.2** |

La subida de `confidence` hay que leerla con cuidado: al prompt se le dice que con
tags puede subirlo a la zona media, así que parte del salto es obediencia. La
evidencia más dura es la dispersión de los ejes, que nadie le pidió que ampliara:
`danceability` +3.2, `tempo_feel` +2.5, `energy` +2.0. Los perfiles discriminan más.

Lo que Last.fm **no** arregla: los artistas que el modelo desconoce por completo
tampoco están en Last.fm, y los contextos siguen sobreasignados (`fiesta` aparece en
el 57% de la muestra). Está anotado en `HANDOFF.md` como el problema abierto
principal.

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
suelta y corta. Last.fm es gratis.

El campo **Analizar como máx.** limita cuántas canciones se etiquetan por pasada:
empieza corto y comprueba la calidad antes de pagar el barrido completo.

## Ajustes útiles

| Parámetro | Qué hace |
|---|---|
| **Nota mínima** | Sube a 70 para una selección corta y muy fiel; baja a 40 si sale vacía |
| **Máx. por artista** | Evita que un disco cope la playlist entera |
| `order: flow` | Ordena por energía ascendente (curva de escucha) en vez de por afinidad |

Tocar los ejes o los contextos en `app/vibes.py`, o lo que ve el etiquetador,
invalida las etiquetas guardadas: sube `TAGGER_VERSION` y se re-etiquetará sólo lo
necesario.

## Tests

```bash
./.venv/bin/python -m pytest tests/ -q
```

55 tests sobre el scorer, la capa SQLite, el etiquetador, el cliente de Last.fm y el
recorrido HTTP completo. Ninguno llama a las APIs de Spotify, Claude ni Last.fm.

Para medir la calidad del etiquetado sobre tu música:

```bash
./.venv/bin/python scripts/vibes_report.py --snapshot          # antes de re-etiquetar
./.venv/bin/python scripts/vibes_report.py data/snapshots/...  # comparar después
```

## Estructura

| Fichero | Responsabilidad |
|---|---|
| `app/vibes.py` | Vocabulario y esquemas Pydantic compartidos |
| `app/spotify.py` | OAuth PKCE, paginación, rate limiting, creación de playlists |
| `app/lastfm.py` | Tags de comunidad de álbum y artista |
| `app/db.py` | Cache SQLite de biblioteca, etiquetas y tags |
| `app/tagger.py` | Las dos llamadas a Claude: etiquetar y traducir la petición |
| `app/matcher.py` | Puntuación y selección (sin LLM) |
| `app/main.py` | API FastAPI |
| `scripts/vibes_report.py` | Informe de calidad del etiquetado |
