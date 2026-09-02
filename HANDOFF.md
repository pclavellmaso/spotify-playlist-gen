# Handoff — Playlists por momento

Documento de traspaso. Contiene todo el contexto necesario: no hace falta la
conversación original.

Escrito el 31 de agosto de 2026. **Actualizado el 1 de septiembre de 2026**, tras
la primera sesión que lo ejerció de verdad contra las APIs reales — que encontró
tres bugs y cambió varias conclusiones de la versión anterior. Lo que ha cambiado
está marcado con ⚠.

---

## 1. Empezar en 5 minutos

```bash
git clone https://github.com/pclavellmaso/spotify-playlist-gen
cd spotify-playlist-gen
git checkout main

uv venv --python 3.13 .venv                     # ver el aviso de abajo
uv pip install --python .venv/bin/python -r requirements.txt

cp .env.example .env      # rellenar las claves (ver §2)
./.venv/bin/python -m pytest tests/ -q   # deben pasar 55
./.venv/bin/python run.py                # abre http://127.0.0.1:8000
```

⚠ **Sobre el entorno de Python.** El `python3 -m venv` de toda la vida puede no
servir. En el Mac donde se montó esto (macOS 26) el único Python del sistema es
3.9.6, demasiado antiguo para `anthropic` 1.x; y el `python@3.13` de Homebrew se
instala pero está roto — su `pyexpat` enlaza contra un `/usr/lib/libexpat.1.dylib`
que en macOS 26 no expone los símbolos que espera, así que `ensurepip` falla y no
se puede crear ningún venv. La salida limpia es `uv`, que trae su propio CPython
autocontenido (`brew install uv`). En otra máquina con un Python 3.10+ sano,
`python -m venv` sirve igual.

---

## 2. Configuración necesaria

**`SPOTIFY_CLIENT_ID`** — crea una app en
[developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
No hace falta el client secret (se usa PKCE). En la config de la app añade como
Redirect URI **exactamente**:

```
http://127.0.0.1:8000/api/auth/callback
```

Spotify ya no acepta `localhost`: tiene que ser la IP de loopback `127.0.0.1`.
Si no coincide carácter por carácter, el login falla con `INVALID_CLIENT`.

Al crear la app, marca **Web API** y nada más. Ojo: en el dashboard hay una
sección aparte llamada *Spotify Soloist API Key* (un cliente de Spotify Connect
para terminal, de agosto de 2026) que no tiene nada que ver. Lo que buscas se
llama **Client ID**, son 32 caracteres hexadecimales, y no se genera con un
botón: ya lo tiene la app que acabas de crear.

**`ANTHROPIC_API_KEY`** — de [console.anthropic.com](https://console.anthropic.com).
Tiene que haber **saldo** en *Plans & Billing*; sin créditos, cada llamada
devuelve un 400 y no se etiqueta nada.

⚠ **`LASTFM_API_KEY`** (opcional pero recomendable) — gratuita para uso no
comercial en [last.fm/api/account/create](https://www.last.fm/api/account/create).
Los campos de callback y homepage pueden ir vacíos: no se usa autenticación de
usuario. Sin esta key la app funciona exactamente igual que antes, solo que el
etiquetado es peor en catálogo poco conocido (ver §3).

Opcional: `ANTHROPIC_MODEL` (por defecto `claude-opus-5`).

### Uso

En la web, en este orden: **Sincronizar** (baja la biblioteca) → **Analizar
pendientes** (etiqueta con Claude; tarda, puedes cerrar y volver) → escribe el
momento → **Generar** → **Guardar en Spotify**.

Ojo con la confusión más fácil: *Analizar* **no crea ninguna playlist**, solo
etiqueta en local. *Generar* tampoco guarda nada, solo enseña la selección. La
playlist se crea únicamente al pulsar *Guardar en Spotify*, con el nombre del
campo de texto —precargado con el `label` que propone el modelo— y al terminar
aparece el enlace para abrirla.

---

## 3. Contexto crítico: los límites de las APIs

Esto es lo más importante del documento. Explica por qué el proyecto está hecho
así y evita que la próxima sesión pierda tiempo en callejones sin salida.

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
metadatos (artista, título, álbum, año) más los tags de Last.fm. Es una
*estimación*, no una medición. Por eso cada etiqueta lleva un `confidence` y el
scorer arrastra hacia neutro las canciones que el modelo no reconoce, en lugar de
dejar que decidan.

Alternativas descartadas: AcousticBrainz (dataset congelado en 2022),
Essentia/librosa (requiere el audio, que Spotify no da), y servicios comerciales
de pago tipo Musicae o SoundNet.

### ⚠ En Last.fm, los tags por canción no existen

Last.fm sí se usa (§4), pero **no como estaba previsto**. `track.getTopTags`
devuelve una lista vacía de forma sistemática, y el `toptags` de `track.getInfo`
también. No es cosa de un catálogo nicho: comprobado contra Santana *Smooth*
(254.000 oyentes) y Lizzo *Juice* (664.000), ambos vacíos.

Lo que sí está lleno y es útil es `album.getTopTags` y `artist.getTopTags`. El
proyecto consulta esos dos y los combina.

> Si una sesión futura propone `track.getTopTags` "porque es lo más específico",
> ya se probó y no devuelve nada.

La contrapartida: dos canciones del mismo disco reciben los mismos tags. Sitúan
el género, la escena y la época, pero no distinguen una balada de un corte
bailable del mismo álbum. Al prompt del etiquetador se le dice explícitamente.

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
Spotify ──sync──▶ SQLite ──┬── Last.fm (álbum + artista) ──┐
                           │                               ▼
                           └──────────── Claude (una vez por canción) ──▶ perfil
                                                                            │
tu frase ──Claude──▶ perfil objetivo ──distancia ponderada──▶ selección ──▶ playlist
```

Tres decisiones de diseño que conviene no romper sin querer:

**1. El etiquetado se cachea de forma permanente.** Cada canción se analiza una
sola vez y el resultado vive en SQLite. El coste está en la ingesta inicial, no
en el uso: las consultas posteriores sólo llaman al modelo para interpretar tu
frase. Si tocas los ejes o contextos de `app/vibes.py`, o lo que ve el
etiquetador, **sube `TAGGER_VERSION`** — eso invalida el cache y re-etiqueta sólo
lo necesario. Va por la **2** (la 1 no tenía Last.fm).

**2. El emparejamiento no usa LLM.** Es una distancia ponderada sobre siete ejes
fijos, determinista y con tests. El LLM sólo traduce (canción → perfil, frase →
perfil objetivo); comparar es aritmética. Esto mantiene el sistema barato,
predecible y testeable.

**3. ⚠ Lo que el modelo rellena tiene que tener campos con nombre.** Ver el bug
del `dict` abierto en §5. Si añades algo que el modelo deba producir, no uses un
diccionario libre: dale un campo por clave posible.

### El espacio de vibes (`app/vibes.py`)

Siete ejes 0-100: `energy`, `valence`, `danceability`, `acousticness`,
`tempo_feel` (velocidad *percibida*, no BPM), `vocal_focus`, `warmth`.

Quince contextos cerrados: `piscina_verano`, `terraza_atardecer`, `fiesta`,
`after_hours`, `cena_amigos`, `romantico`, `concentracion_trabajo`,
`entrenamiento`, `conducir`, `viaje_carretera`, `desayuno_domingo`,
`tareas_casa`, `melancolia_lluvia`, `meditacion`, `dormir`.

Más hasta 6 descriptores libres en castellano por canción.

`QueryDraft` es lo que produce el modelo al interpretar tu frase; `VibeQuery` es
la forma que consume el scorer. La conversión está en `QueryDraft.to_query()`.

### Ficheros

| Fichero | Responsabilidad |
|---|---|
| `app/vibes.py` | Vocabulario y esquemas Pydantic compartidos. **Tocar aquí = subir `TAGGER_VERSION`** |
| `app/spotify.py` | OAuth PKCE, paginación, rate limiting (429 + `Retry-After`), crear playlists |
| `app/lastfm.py` | ⚠ Tags de comunidad de álbum y artista. Sin key, se desactiva en silencio |
| `app/db.py` | Cache SQLite: biblioteca, etiquetas y tags de Last.fm |
| `app/tagger.py` | Las dos llamadas a Claude: `tag_batch` y `parse_query` |
| `app/matcher.py` | Puntuación y selección. Sin LLM |
| `app/main.py` | API FastAPI + job de etiquetado en background |
| `app/static/` | Front en HTML/CSS/JS a pelo, sin framework |
| `scripts/vibes_report.py` | ⚠ Informe de calidad del etiquetado y comparación contra snapshots |

### Detalles ya resueltos (no re-hacer)

- OAuth **PKCE** con validación de `state` (anti-CSRF)
- Refresh automático del token; Spotify no reenvía el `refresh_token` al
  refrescar, y eso está contemplado
- Rate limiting: respeta el `Retry-After` de los 429, reintentos con backoff.
  Last.fm se consulta a 4 req/s como mucho, por debajo del límite de su ToS
- Filtrado de podcasts, tracks locales y retirados (no tienen id usable)
- El modelo puede alucinar o repetir un `track_id`: se filtra contra los pedidos
- ⚠ Los errores permanentes del etiquetado (sin saldo, key inválida, modelo
  inexistente) abortan en el primer lote; los transitorios se saltan, pero tres
  seguidos abortan también
- ⚠ Last.fm se cachea por entidad (`artist:x`, `album:x|y`), incluidas las
  respuestas vacías: que no conozcan un artista es una respuesta
- Tope por artista, con relleno si la diversidad deja la lista corta
- Orden por curva de energía (`order: "flow"`) en vez de por afinidad

---

## 5. ⚠ Estado actual

**55 tests en verde**, y —a diferencia de la versión anterior de este
documento— **el flujo real contra Spotify y Anthropic ya se ha ejercido**:
OAuth completo, sync de 1.789 canciones, etiquetado, generación y scoring.

- `tests/test_matcher.py` (9) — scoring, veto por descriptor, efecto del
  `confidence`, tope por artista, relleno, orden, filtro por nota mínima
- `tests/test_db.py` (5) — upsert idempotente, invalidación por
  `TAGGER_VERSION`, normalización de descriptores, stats
- `tests/test_api.py` (4) — recorrido HTTP completo de `/api/generate`
- `tests/test_tagger.py` (21) — política de errores, `parse_query`, filtrado de
  ids alucinados, contexto de Last.fm en el prompt
- `tests/test_lastfm.py` (16) — cliente, filtrado de tags, cache por entidad

Ningún test toca las APIs de Spotify, Claude ni Last.fm.

### Los tres bugs que encontró la validación real

Merece la pena leerlos: los tres eran invisibles desde los tests y ninguno se
habría encontrado sin ejercer el flujo de verdad.

**1. Un etiquetado sin saldo terminaba "sin errores".** `tag_all` capturaba
cualquier `APIError` por lote y seguía. Con la cuenta de Anthropic sin créditos,
los 45 lotes de la biblioteca fallaban uno a uno, el job terminaba sin etiquetar
nada y `_job["error"]` se quedaba en `None`: la UI solo mostraba una barra
clavada en 0% que luego desaparecía. Arreglado separando errores permanentes de
transitorios.

**2. `targets` llegaba vacío y el 65% de la nota desaparecía.** Este es el
importante. `VibeQuery.targets` era un `dict[str, int]`, que en JSON Schema se
traduce a un objeto con `additionalProperties` y **ni una sola propiedad con
nombre**: los siete ejes solo existían en la prosa del system prompt, no en el
esquema que guía la generación. El modelo devolvía `{}` sistemáticamente y
razonaba los ejes en `notes`, el único campo donde tenía sitio para escribirlos.
Con `_axes_score` devolviendo `None`, la selección la decidían los contextos.
Una petición de "calma en la piscina" devolvía Papi Chulo y *Life Is a Party*,
todas por compartir la etiqueta `piscina_verano`. Insistir en el prompt no lo
arreglaba; lo arregló `QueryDraft`, con un campo por eje.

**3. `requirements.txt` no traía `httpx`.** El `TestClient` de Starlette lo
necesita, y `httpx2` (el del SDK de anthropic) es otro paquete. En un entorno
limpio los tests no llegaban ni a colectarse.

### ⚠ Lo que sabemos de la calidad del etiquetado

Medido sobre 90 canciones reales de la biblioteca, **sin** Last.fm:

```
confidence   media 30.8 · mediana 25 · dos tercios por debajo de 40
```

La causa: la biblioteca es house, DnB y electrónica reciente de sello pequeño,
con mucho 2025-2026. El modelo no reconoce los temas, baja el `confidence` —que
es la señal correcta— pero el perfil que devuelve acaba siendo el prior del
género: los ejes de las canciones con confianza baja convergen todos al mismo
sitio.

Dos síntomas más, independientes de Last.fm y **sin resolver**:

- **Contextos sobreasignados.** Ninguna de las 90 se quedó con la lista vacía,
  pese a que el prompt dice que vacío es válido. Casi todas llevan 3-4.
  `fiesta` en el 52% de la muestra, `terraza_atardecer` en el 46%. Si medio
  catálogo es "fiesta", ese bloque —el 20% de la nota— no distingue nada. Y un
  acierto de contexto puntúa 100 plano, sin matiz.
- **Ejes comprimidos.** `danceability` con media 75.8 y mínimo 48: ni una sola
  canción etiquetada como poco bailable. Parte es el gusto real, parte es rango
  desaprovechado.

Usa `scripts/vibes_report.py` para volver a medir esto en cualquier momento.
Guarda un snapshot **antes** de re-etiquetar: `save_vibes` sobrescribe por
`track_id` y si no, la comparación se pierde.

```bash
./.venv/bin/python scripts/vibes_report.py --snapshot
./.venv/bin/python scripts/vibes_report.py data/snapshots/vibes-2026-09-01.json
```

### Pendiente administrativo (1 clic, en GitHub)

El repo estaba vacío al empezar, así que no existía `main`. La rama por defecto
sigue siendo `claude/spotify-playlist-mood-filter-qigroz`. Un `git clone` cae en
esa rama, no en `main`. Para arreglarlo:

1. `github.com/pclavellmaso/spotify-playlist-gen/settings` → *General* →
   *Default branch* → cambiar a `main`
2. En *Branches*, borrar `claude/spotify-playlist-mood-filter-qigroz`

No hay `gh` instalado en la máquina, así que es manual.

---

## 6. ⚠ Siguientes pasos sugeridos

Por orden de valor, actualizado con lo que se sabe ahora:

1. **Apretar el vocabulario de contextos.** Es el problema abierto más grande.
   Opciones: pedir al etiquetador un máximo de 2 contextos y sólo si encajan de
   verdad; puntuar el acierto de contexto de forma graduada en vez de 100 plano;
   o partir los contextos demasiado anchos — `piscina_verano` cubre a la vez
   "chill en la piscina" y "fiesta en la piscina", que son cosas distintas.
   Cuidado: tocar `CONTEXTS` obliga a subir `TAGGER_VERSION` y re-etiquetar.
2. **Excluir canciones ya usadas** — para que dos playlists del mismo tipo no
   salgan idénticas.
3. **Feedback del usuario** — un "esta no encaja" que ajuste el perfil guardado.
4. **Batch API de Anthropic** — 50% más barato para el etiquetado masivo, que es
   asíncrono por naturaleza. Vale la pena si acabas etiquetando miles de temas.
5. **Combinar varias fuentes** — ahora se filtra sobre una sola (likes *o* una
   playlist).

Lo que **no** merece la pena: buscar más fuentes de tags para la cola del
catálogo. Los artistas que el modelo no conoce en absoluto (Vesyr, KALEYA SYSTEM,
Mx Cartier) tampoco están en Last.fm. Con más de la mitad de las entidades
consultadas devolviendo vacío, esa cola probablemente no tenga arreglo por la vía
de los metadatos.

### Ajustes rápidos sin tocar código

| Parámetro | Efecto |
|---|---|
| **Nota mínima** | 70 = selección corta y muy fiel · 40 = más amplia si sale vacía |
| **Máx. por artista** | Evita que un disco cope la playlist |
| **Analizar como máx.** | Tope de canciones por pasada. Empieza corto: valida la calidad antes de pagar el barrido completo |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` abarata mucho el barrido inicial, a cambio de precisión en catálogo poco conocido |

---

## 7. Avisos

- **`data/` está en `.gitignore` y debe seguir así.** Contiene la base SQLite,
  los snapshots de etiquetas y `data/token.json` con tu token de OAuth de Spotify
  (permisos `0600`). Nunca debe subirse a GitHub. Igual que `.env` con las claves
- Todo corre en local; nada sale de tu máquina salvo las llamadas a las APIs de
  Spotify, Anthropic y Last.fm
- El SDK `anthropic` 1.x usa `httpx2`, no `httpx`. Si añades código HTTP, importa
  `httpx2` (así lo hacen `app/spotify.py` y `app/lastfm.py`). `httpx` a secas
  está en `requirements.txt` sólo porque lo necesita el `TestClient` de Starlette
- Se usa `client.messages.parse(output_format=ModeloPydantic)` y se lee
  `response.parsed_output`, que puede ser `None`: hay que comprobarlo
- La barra de progreso avanza **por lote de 40**, no por canción, porque el
  modelo devuelve el lote entero de una vez y dentro de él no hay progreso
  observable. Bajar `BATCH_SIZE` daría una barra más fina y multiplicaría el
  coste: se perdería el cacheo del prefijo del prompt

---

## 8. Gemini: el proveedor que falta

`app/llm.py` cubre hoy dos dialectos: el SDK de Anthropic y `/chat/completions`
(OpenAI, OpenRouter, Groq, LM Studio, Ollama). **Google Gemini no está**, y no
entra por el adaptador OpenAI: necesita el suyo.

Merece la pena por una razón concreta ligada al problema medido en §5. La
biblioteca es house, DnB y electrónica reciente de sello pequeño, el
`confidence` medio está en 30.8, y la causa es que **el modelo no reconoce los
temas**. Ollama ya te da gratis, pero un `llama3.1` local conoce *menos* catálogo
que un modelo grande, no más — va en la dirección contraria al problema. Gemini
es la única opción que es **gratis y a la vez un modelo grande de nube**:

| Proveedor | Cuota gratuita | Estado |
|---|---|---|
| **Gemini** | 2.5 Flash, ~1.500 req/día | **Sin implementar.** Salida estructurada con esquema JSON, que es lo que usa el tagger |
| **Groq** | 14.400 req/día | Ya soportado. `.env.example` lo vende como "rápido y barato" pero no dice que tiene tier gratuito |
| **OpenRouter** | 28+ modelos gratuitos | Ya soportado. Cómodo para barrer varios de golpe |
| **Ollama / LM Studio** | Ilimitado, local | Ya soportado. Gratis de verdad, pero menos conocimiento musical |
| **DeepSeek** | Sin tier gratis | ~$0.44/M tokens de entrada |

Con lotes de 40 canciones, 1.500 req/día son 60.000 canciones diarias. La cuota
no es el cuello de botella aquí.

**La pregunta abierta que esto plantea**, y que `scripts/comparar_modelos.py` ya
puede responder: ¿reconoce Gemini más de *tu* cola de catálogo que Claude? Si la
respuesta es no, confirma lo que dice §6 —que esa cola no tiene arreglo por la
vía de los metadatos— y deja de ser una vía a explorar. Si es sí, cambia el
proveedor por defecto y de paso abarata el barrido a cero.

**Aviso**: los tiers gratuitos suelen entrenar con los datos enviados. Son
metadatos musicales públicos y poco sensibles, pero si algún día distribuyes la
app (§9) hay que decirlo.

---

## 9. Distribución: el modelo BYOK

Cada usuario crea su propia app de Spotify y trae sus propias claves, en vez de
compartir las tuyas. Así cada uno tiene su cuota de 5 usuarios, en la que sólo
está él, y el tope de §3 deja de ser un problema. Es el patrón estándar de las
herramientas open source y es la vía correcta: distribuir tu Client ID sí estaría
mal, y esto lo evita.

Mueve el techo de sitio, no lo elimina:

- **Cada usuario necesita Spotify Premium**, porque en BYOK cada usuario *es* el
  desarrollador. *Decisión tomada: asumible, la mayoría paga Premium.*
- **Un solo Client ID en Development Mode por cuenta.** Si el usuario ya tiene
  otra app de dev, el dashboard le impedirá crear ésta.
- **El techo real es el onboarding**: Premium → cuenta de dev → crear app →
  Client ID → redirect URI exacto → añadirse como test user → clave del LLM →
  `.env`. Por eso el arranque con doble clic y una clave gratuita (§8) valen
  más de lo que parece: atacan el muro, no el tope de usuarios.

**"Público" son dos cosas y sólo una funciona:** open source en GitHub y que cada
uno se lo instale, sí. Un servicio hosted en tu dominio, no — custodiarías tokens
de Spotify y claves de API ajenas, que son credenciales de facturación.

### ⚠ Pendiente: leer los términos de Spotify

**Sin verificar.** No se pudieron leer desde el entorno donde se escribió esto
(`developer.spotify.com` bloqueado por política de red). Versión vigente: v10,
efectiva el 15 de mayo de 2025, en `developer.spotify.com/terms`.

Qué mirar, por orden de riesgo:

1. **Para qué está permitido Development Mode.** Es la clave de todo el
   planteamiento BYOK: si lo acota a *desarrollo y pruebas*, usarlo como
   herramienta cotidiana queda en zona gris — por el propósito, no por el número
   de usuarios
2. **La cláusula de machine learning / IA.** Es literalmente lo que hace la app:
   mandar metadatos de Spotify a un modelo externo. No se entrena nada, sólo se
   clasifica, y esa distinción suele importar en el texto
3. **Compartir o distribuir credenciales**, que debería confirmar que BYOK es lo
   correcto
4. **Retención y caché de metadatos.** La BD guarda títulos, artistas y álbumes
   indefinidamente

---

## 10. Móvil

El front ya es responsive. El problema es que el backend es Python.

**Hoy, cambiando una línea:** `APP_HOST=0.0.0.0` y accedes desde el móvil por la
IP del PC en la misma WiFi. El truco es que **el móvil nunca hace login**: haces
el OAuth una vez en el PC —donde `127.0.0.1` sí es válido—, el token queda en
`data/token.json` y desde el móvil sólo abres la web.

No se puede hacer el OAuth desde el móvil: desde abril de 2025 Spotify **sólo
acepta HTTP en direcciones de loopback**, así que un `http://192.168.x.x:8000`
lo rechaza como *insecure redirect URI*.

> ⚠ Con `0.0.0.0` la app queda accesible **sin contraseña** a cualquiera en la
> red, con el token de Spotify dentro. Asumible en casa; no en una oficina.

Un `manifest.json` + icono + service worker permitirían *Añadir a pantalla de
inicio* en Android e iOS: icono propio, pantalla completa, sin barra de
navegador. Es lo más parecido a "instalarla" y es poco trabajo.

**App nativa: el empaquetado de escritorio no se traslada.** Tauri 2 soporta
iOS y Android, pero el patrón *sidecar* (lanzar Python como subproceso) no existe
en móvil: iOS no permite ejecutar binarios arbitrarios y en Android es frágil.
Habría que **portar el backend**, que es menos de lo que parece — HTTP a Spotify,
SQLite, llamadas al LLM y aritmética; `app/matcher.py` son ~100 líneas de
matemáticas sin dependencias. Si el móvil llega a ser un objetivo real, la
decisión es reescribir el backend en TypeScript y usar Capacitor o Tauri: el
trabajo es pequeño *ahora* y crece cada semana que se siga añadiendo a la versión
Python.

**Riesgo si apuntas a iOS**, sin confirmar: Apple suele rechazar apps que exigen
al usuario conseguir credenciales de API por su cuenta antes de poder usarlas.
Google Play es más permisivo.
