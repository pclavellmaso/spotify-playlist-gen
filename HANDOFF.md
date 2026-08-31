# Handoff — Playlists por momento

Documento de traspaso para continuar el proyecto en Claude Code desde el PC.
Escrito el 31 de agosto de 2026. Contiene todo el contexto necesario: no hace
falta la conversación original.

---

## 1. Empezar en 5 minutos

```bash
git clone https://github.com/pclavellmaso/spotify-playlist-gen
cd spotify-playlist-gen
git checkout main

python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env      # rellenar las dos claves (ver §2)
python -m pytest tests/ -q   # deben pasar 18
python run.py             # abre http://127.0.0.1:8000
```

Luego, en Claude Code dentro de esa carpeta:

```
claude
```

**Primer prompt sugerido para la nueva sesión** (cópialo tal cual):

> Lee HANDOFF.md y README.md para el contexto. Es una web app local que genera
> playlists de Spotify filtrando mi biblioteca según una descripción en lenguaje
> natural del momento ("calma en la piscina con cervecita"). Está funcionando y
> con 18 tests en verde. IMPORTANTE: Spotify retiró `audio-features` en 2024, no
> intentes usarlo. Quiero [describe aquí lo que quieras hacer].

---

## 2. Configuración necesaria

Dos credenciales en `.env`:

**`SPOTIFY_CLIENT_ID`** — crea una app en
[developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
No hace falta el client secret (se usa PKCE). En la config de la app añade como
Redirect URI **exactamente**:

```
http://127.0.0.1:8000/api/auth/callback
```

Spotify ya no acepta `localhost`: tiene que ser la IP de loopback `127.0.0.1`.
Si no coincide carácter por carácter, el login falla con `INVALID_CLIENT`.

**`ANTHROPIC_API_KEY`** — de [console.anthropic.com](https://console.anthropic.com).

Opcional: `ANTHROPIC_MODEL` (por defecto `claude-opus-5`).

### Uso

En la web, en este orden: **Sincronizar** (baja la biblioteca) → **Analizar
pendientes** (etiqueta con Claude; tarda, puedes cerrar y volver) → escribe el
momento → **Generar** → **Guardar en Spotify**.

---

## 3. Contexto crítico: las dos limitaciones de la API

Esto es lo más importante del documento. Explica por qué el proyecto está hecho
así y evita que la próxima sesión pierda tiempo en un callejón sin salida.

### `audio-features` está muerto

Spotify **retiró el 27 de noviembre de 2024** los endpoints `audio-features`,
`audio-analysis`, `recommendations`, `related-artists` y `featured-playlists`
para toda app nueva. Sigue sin haber reemplazo oficial.

El enfoque clásico de este tipo de proyecto —pedir el vector acústico de cada
canción (energy, valence, danceability, tempo) y filtrar por umbrales— **ya no es
posible**. Todos los tutoriales que encuentres online son anteriores a esa fecha
y no funcionan.

> Si en una sesión futura Claude propone usar `audio-features`, está tirando de
> memoria de entrenamiento. Recuérdaselo.

**Alternativa adoptada:** el perfil sonoro lo infiere Claude a partir de los
metadatos (artista, título, álbum, año). Es una *estimación*, no una medición.
Por eso cada etiqueta lleva un `confidence` y el scorer arrastra hacia neutro las
canciones que el modelo no reconoce, en lugar de dejar que decidan.

Alternativas descartadas, por si alguna vez interesan: Last.fm (tags de la
comunidad, API gratuita — sería un buen complemento), AcousticBrainz (dataset
congelado en 2022), Essentia/librosa (requiere el audio, que Spotify no da), y
servicios comerciales de pago tipo Musicae o SoundNet.

### Developer Mode: 5 usuarios, y Premium obligatorio

Cambios de febrero de 2026, efectivos el 9 de marzo:

- El desarrollador necesita cuenta **Premium**
- **5 usuarios de prueba** máximo por app (antes eran 25)
- Salir de ahí requiere *extended quota*: empresa registrada y **250.000
  usuarios activos mensuales**

**Conclusión: esto no puede ser un producto público hoy.** Como herramienta
personal (tú y 4 personas más) funciona perfectamente. Merece la pena tenerlo
claro antes de invertir en, por ejemplo, un sistema de cuentas o un deploy.

Lo que **sí** sigue disponible en Developer Mode y usa el proyecto: perfil
(`/me`), likes (`/me/tracks`), playlists propias y creación de playlists.

---

## 4. Cómo funciona

```
Spotify ──sync──▶ SQLite ──Claude (una vez por canción)──▶ perfil de vibe
                                                                │
tu frase ──Claude──▶ perfil objetivo ──distancia ponderada──▶ selección ──▶ playlist
```

Dos decisiones de diseño que conviene no romper sin querer:

**1. El etiquetado se cachea de forma permanente.** Cada canción se analiza una
sola vez y el resultado vive en SQLite. El coste está en la ingesta inicial, no
en el uso: las consultas posteriores sólo llaman al modelo para interpretar tu
frase. Si tocas los ejes o contextos de `app/vibes.py`, **sube `TAGGER_VERSION`**
— eso invalida el cache y re-etiqueta sólo lo necesario.

**2. El emparejamiento no usa LLM.** Es una distancia ponderada sobre siete ejes
fijos, determinista y con tests. El LLM sólo traduce (canción → perfil, frase →
perfil objetivo); comparar es aritmética. Esto mantiene el sistema barato,
predecible y testeable.

### El espacio de vibes (`app/vibes.py`)

Siete ejes 0-100: `energy`, `valence`, `danceability`, `acousticness`,
`tempo_feel` (velocidad *percibida*, no BPM), `vocal_focus`, `warmth`.

Quince contextos cerrados: `piscina_verano`, `terraza_atardecer`, `fiesta`,
`after_hours`, `cena_amigos`, `romantico`, `concentracion_trabajo`,
`entrenamiento`, `conducir`, `viaje_carretera`, `desayuno_domingo`,
`tareas_casa`, `melancolia_lluvia`, `meditacion`, `dormir`.

Más hasta 6 descriptores libres en castellano por canción.

### Ficheros

| Fichero | Responsabilidad |
|---|---|
| `app/vibes.py` | Vocabulario y esquemas Pydantic compartidos. **Tocar aquí = subir `TAGGER_VERSION`** |
| `app/spotify.py` | OAuth PKCE, paginación, rate limiting (429 + `Retry-After`), crear playlists |
| `app/db.py` | Cache SQLite: biblioteca + etiquetas |
| `app/tagger.py` | Las dos llamadas a Claude: `tag_batch` y `parse_query` |
| `app/matcher.py` | Puntuación y selección. Sin LLM |
| `app/main.py` | API FastAPI + job de etiquetado en background |
| `app/static/` | Front en HTML/CSS/JS a pelo, sin framework |

### Detalles ya resueltos (no re-hacer)

- OAuth **PKCE** con validación de `state` (anti-CSRF)
- Refresh automático del token; Spotify no reenvía el `refresh_token` al
  refrescar, y eso está contemplado
- Rate limiting: respeta el `Retry-After` de los 429, reintentos con backoff
- Filtrado de podcasts, tracks locales y retirados (no tienen id usable)
- El modelo puede alucinar o repetir un `track_id`: se filtra contra los pedidos
- Un lote fallido no tumba un sync de 2.000 canciones; se reintenta en la
  siguiente pasada
- Tope por artista, con relleno si la diversidad deja la lista corta
- Orden por curva de energía (`order: "flow"`) en vez de por afinidad

---

## 5. Estado actual

**Funciona y está testeado.** 18 tests en verde:

- `tests/test_matcher.py` (9) — scoring, veto por descriptor, efecto del
  `confidence`, tope por artista, relleno, orden, filtro por nota mínima
- `tests/test_db.py` (5) — upsert idempotente, invalidación por
  `TAGGER_VERSION`, normalización de descriptores, stats
- `tests/test_api.py` (4) — recorrido HTTP completo de `/api/generate` con la
  llamada a Claude sustituida; el resto se ejerce de verdad

Ningún test toca las APIs de Spotify ni de Claude.

**Lo que NO se ha probado nunca**: el flujo real contra Spotify (OAuth, sync de
una biblioteca de verdad) y la calidad real del etiquetado sobre música concreta.
Requiere las credenciales, que están en tu PC, no en el entorno donde se
desarrolló. **Esa es la primera validación que deberías hacer.**

### Pendiente administrativo (1 clic, en GitHub)

El repo estaba vacío al empezar, así que no existía `main`. La rama por defecto
sigue siendo `claude/spotify-playlist-mood-filter-qigroz`, aunque `main` ya
existe con el mismo commit (`2849a09`). Para arreglarlo:

1. `github.com/pclavellmaso/spotify-playlist-gen/settings` → *General* →
   *Default branch* → cambiar a `main`
2. En *Branches*, borrar `claude/spotify-playlist-mood-filter-qigroz`

Ambas ramas son idénticas, así que es puramente cosmético.

---

## 6. Siguientes pasos sugeridos

**Primero, y por encima de todo: validar la calidad del etiquetado.** Sincroniza,
etiqueta unas 50 canciones (`POST /api/tag` acepta `limit`) y mira si los
perfiles tienen sentido *para tu música*. Todo lo demás depende de esto. Si con
tu catálogo el `confidence` sale bajo de forma sistemática, el enfoque necesita
ayuda y ahí es donde entran los tags de Last.fm.

Después, por orden de valor:

1. **Enriquecer con Last.fm** — API gratuita, tags de la comunidad (`chill`,
   `summer`, `balearic`). Pasárselos al tagger como contexto adicional subiría
   mucho la precisión en música que el modelo no conoce bien
2. **Excluir canciones ya usadas** — para que dos playlists del mismo tipo no
   salgan idénticas
3. **Feedback del usuario** — un "esta no encaja" que ajuste el perfil guardado
4. **Batch API de Anthropic** — 50% más barato para el etiquetado masivo, que es
   asíncrono por naturaleza. Vale la pena si acabas etiquetando miles de temas
5. **Combinar varias fuentes** — ahora se filtra sobre una sola (likes *o* una
   playlist)

### Ajustes rápidos sin tocar código

| Parámetro | Efecto |
|---|---|
| **Nota mínima** | 70 = selección corta y muy fiel · 40 = más amplia si sale vacía |
| **Máx. por artista** | Evita que un disco cope la playlist |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` abarata mucho el barrido inicial, a cambio de precisión en catálogo poco conocido |

---

## 7. Avisos

- **`data/` está en `.gitignore` y debe seguir así.** Contiene la base SQLite y
  `data/token.json` con tu token de OAuth de Spotify (permisos `0600`). Nunca
  debe subirse a GitHub. Igual que `.env` con las dos API keys
- Todo corre en local; nada sale de tu máquina salvo las llamadas a las APIs de
  Spotify y Anthropic
- El SDK `anthropic` 1.x usa `httpx2`, no `httpx`. Si añades código HTTP, importa
  `httpx2` (así lo hace `app/spotify.py`)
- Se usa `client.messages.parse(output_format=ModeloPydantic)` y se lee
  `response.parsed_output`, que puede ser `None`: hay que comprobarlo
