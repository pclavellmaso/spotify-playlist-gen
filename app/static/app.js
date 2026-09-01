const $ = (id) => document.getElementById(id);
const show = (el, visible) => el.classList.toggle("hidden", !visible);

let current = null;      // última respuesta de selección
let modo = "new";        // "new" | "extend"
let yo = "";             // nombre de usuario, para filtrar listas ajenas

const EJEMPLOS = [
  "resaca de domingo con las persianas bajadas",
  "conduciendo de noche por la costa",
  "cocinando para gente que me cae bien",
  "última hora en una terraza que no quiere cerrar",
  "martes por la mañana, concentración y nada de voces",
  "calentando antes de salir de casa",
  "lluvia contra la ventana y ninguna prisa",
  "sobremesa larga que se alarga más",
  "kilómetro doce de una carrera larga",
  "bajando revoluciones antes de dormir",
  "primer café, sin hablar con nadie todavía",
  "sesión de tarde en una piscina vacía",
];

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Error ${res.status}`);
  return body;
}

function setBusy(el, busy, label) {
  el.disabled = busy;
  if (label) el.textContent = label;
}

/* ==================== sesión ==================== */
function setLoggedOut(mensaje) {
  show($("landing"), true);
  document.querySelectorAll(".landing-only").forEach((el) => show(el, true));
  show($("login"), true);
  show($("logout"), false);
  show($("whoami"), false);
  for (const id of ["setup", "generator", "results"]) show($(id), false);
  $("status").innerHTML = mensaje;
}

async function refreshStatus() {
  const s = await api("/api/status");

  if (!s.configured) {
    setLoggedOut("Falta <code>SPOTIFY_CLIENT_ID</code> en tu <code>.env</code>. Los pasos están más abajo.");
    return;
  }
  if (!s.connected) {
    setLoggedOut("Sin sesión. Se abrirá Spotify para que autorices el acceso de solo lectura y escritura de playlists.");
    return;
  }

  yo = s.user || "";
  show($("landing"), false);
  document.querySelectorAll(".landing-only").forEach((el) => show(el, false));
  show($("login"), false);
  show($("logout"), true);
  show($("whoami"), true);
  $("whoami").textContent = s.user;
  show($("setup"), true);
  show($("generator"), true);
  $("status").textContent = `Sesión activa · modelo ${s.model} · ${s.lastfm ? "Last.fm conectado" : "sin Last.fm"}`;

  await loadPlaylists();
  await refreshStats();
}

$("logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.href = "/";
});

/* ==================== biblioteca ==================== */
async function loadPlaylists() {
  if ($("source").options.length > 1) return;
  try {
    const lists = await api("/api/playlists");
    for (const p of lists) {
      const opt = document.createElement("option");
      opt.value = `playlist:${p.id}`;
      opt.textContent = `${p.name} · ${p.total}`;
      $("source").append(opt);

      // Solo se puede escribir en las propias.
      if (!yo || p.owner === yo) {
        const t = document.createElement("option");
        t.value = p.id;
        t.textContent = `${p.name} · ${p.total}`;
        $("target").append(t);
      }
    }
  } catch (err) {
    console.warn("No se pudieron cargar las playlists", err);
  }
}

async function refreshStats() {
  const s = await api(`/api/stats?source=${encodeURIComponent($("source").value)}`);
  $("libstats").textContent =
    `${s.total} indexadas · ${s.tagged} perfiladas · ${s.pending} pendientes`;

  const job = s.job || {};
  const mine = job.source === $("source").value;
  const active = job.running && mine;
  show($("progress"), active);
  if (active && job.total) {
    // El lote en curso aún no cuenta: la barra se queda quieta mientras se
    // espera al modelo, y el rayado indica que sigue vivo.
    $("bar").style.width = `${Math.round((job.done / job.total) * 100)}%`;
    $("bar").classList.add("working");
    $("progtext").textContent =
      `Lote ${job.batch + 1} de ${job.batches} · ${job.done} de ${job.total} perfiladas`;
    setTimeout(refreshStats, 2500);
  } else {
    $("progtext").textContent = "";
  }

  const hecho = !job.running && mine && job.finished && job.done;
  show($("tagdone"), Boolean(hecho));
  if (hecho) $("tagdone").textContent = `${job.done} canciones perfiladas. Ya puedes pedir un momento.`;

  $("taberror").textContent = job.error || "";
  show($("taberror"), Boolean(job.error));
  return s;
}

$("source").addEventListener("change", refreshStats);

$("sync").addEventListener("click", async (e) => {
  setBusy(e.target, true, "Sincronizando…");
  try {
    await api("/api/sync", { method: "POST", body: JSON.stringify({ source: $("source").value }) });
    await refreshStats();
  } catch (err) { alert(err.message); }
  finally { setBusy(e.target, false, "Sincronizar"); }
});

$("tag").addEventListener("click", async (e) => {
  setBusy(e.target, true, "Lanzando…");
  show($("taberror"), false);
  show($("tagdone"), false);
  try {
    const r = await api("/api/tag", {
      method: "POST",
      body: JSON.stringify({ source: $("source").value, limit: Number($("taglimit").value) || null }),
    });
    if (!r.started) alert("No queda nada pendiente de perfilar en este origen.");
    await refreshStats();
  } catch (err) { alert(err.message); }
  finally { setBusy(e.target, false, "Analizar"); }
});

/* ==================== pestañas ==================== */
function setModo(nuevo) {
  modo = nuevo;
  $("tab-new").classList.toggle("is-active", modo === "new");
  $("tab-extend").classList.toggle("is-active", modo === "extend");
  show($("extend-target"), modo === "extend");
  $("prompt").placeholder =
    modo === "extend"
      ? "Opcional: cómo quieres que varíe. «más tranquilo», «menos voces»…"
      : "Describe el momento…";
  show($("chips"), modo === "new");
  $("chat").innerHTML = "";
  show($("results"), false);
  current = null;
}

$("tab-new").addEventListener("click", () => setModo("new"));
$("tab-extend").addEventListener("click", () => setModo("extend"));

/* ==================== ejemplos ==================== */
function pintarChips() {
  const barajadas = [...EJEMPLOS].sort(() => Math.random() - 0.5).slice(0, 4);
  $("chips").innerHTML = "";
  for (const texto of barajadas) {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.type = "button";
    chip.textContent = texto;
    chip.addEventListener("click", () => {
      $("prompt").value = texto;
      $("prompt").focus();
    });
    $("chips").append(chip);
  }
}

let iEjemplo = Math.floor(Math.random() * EJEMPLOS.length);
setInterval(() => {
  // Solo mientras no haya nada escrito: rotar bajo los dedos sería molesto.
  if (modo !== "new" || $("prompt").value) return;
  iEjemplo = (iEjemplo + 1) % EJEMPLOS.length;
  $("prompt").placeholder = EJEMPLOS[iEjemplo];
}, 4200);

/* ==================== conversación ==================== */
function burbuja(quien, contenido, clase = "") {
  const msg = document.createElement("div");
  msg.className = `msg msg-${quien}`;
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = quien === "you" ? "TÚ" : "C";
  const bubble = document.createElement("div");
  bubble.className = `bubble ${clase}`;
  if (typeof contenido === "string") bubble.textContent = contenido;
  else bubble.append(contenido);
  msg.append(avatar, bubble);
  $("chat").append(msg);
  msg.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return msg;
}

const NOMBRE_EJE = {
  energy: "energía", valence: "luminosidad", danceability: "baile",
  acousticness: "acústico", tempo_feel: "tempo", vocal_focus: "voz", warmth: "calidez",
};

function burbujaInterpretacion(result) {
  const cont = document.createElement("div");
  const texto = document.createElement("div");
  texto.textContent = result.query.notes || "Interpretado.";
  cont.append(texto);

  const ejes = document.createElement("div");
  ejes.className = "axes";
  for (const [eje, valor] of Object.entries(result.query.targets || {})) {
    const el = document.createElement("span");
    el.className = "axis";
    el.innerHTML = `${NOMBRE_EJE[eje] || eje} <b>${valor}</b>`;
    ejes.append(el);
  }
  if (ejes.children.length) cont.append(ejes);
  return cont;
}

/* ==================== generación ==================== */
function parametros() {
  const porMinutos = $("sizemode").value === "minutes";
  const n = Number($("limit").value) || 30;
  return {
    source: $("source").value,
    limit: porMinutos ? 100 : n,
    target_minutes: porMinutos ? n : null,
    min_score: Number($("minscore").value),
    max_per_artist: Number($("maxartist").value),
    order: $("order").value,
  };
}

$("sizemode").addEventListener("change", () => {
  const porMinutos = $("sizemode").value === "minutes";
  $("limit").value = porMinutos ? 60 : 30;
  $("limit").max = porMinutos ? 600 : 100;
  $("limit").min = porMinutos ? 5 : 1;
});

$("generate").addEventListener("click", async (e) => {
  const prompt = $("prompt").value.trim();
  if (modo === "new" && !prompt) { $("prompt").focus(); return; }
  if (modo === "extend" && !$("target").value) { alert("Elige una lista a la que añadir."); return; }

  const etiqueta =
    modo === "extend"
      ? `Más como «${$("target").selectedOptions[0].textContent.split(" · ")[0]}»` +
        (prompt ? `, pero ${prompt}` : "")
      : prompt;
  burbuja("you", etiqueta);
  const pensando = burbuja("bot", "Interpretando…", "typing");

  setBusy(e.target, true, "…");
  try {
    const p = parametros();
    current =
      modo === "extend"
        ? await api("/api/extend", {
            method: "POST",
            body: JSON.stringify({ ...p, playlist_id: $("target").value, prompt }),
          })
        : await api("/api/generate", { method: "POST", body: JSON.stringify({ ...p, prompt }) });

    current.limitPedido = p.limit;
    pensando.remove();
    burbuja("bot", burbujaInterpretacion(current));
    $("prompt").value = "";
    $("plname").value = "";
    render(current);
  } catch (err) {
    pensando.remove();
    burbuja("bot", err.message);
  } finally {
    setBusy(e.target, false, "Generar");
  }
});

function render(result) {
  show($("results"), true);
  $("saved").textContent = "";
  $("reslabel").textContent = result.query.label || "Selección";

  const partes = [
    `${result.tracks.length} de ${result.pool} candidatas`,
    `${result.minutes} min`,
    `exigencia ${result.min_score}`,
  ];
  if (result.reference) partes.push(`referencia: ${result.reference} temas de la lista`);
  $("notes").textContent = partes.join(" · ");

  const ampliando = modo === "extend";
  show($("namefield"), !ampliando);
  show($("save"), !ampliando);
  show($("append"), ampliando);
  if (!ampliando && !$("plname").value) $("plname").value = result.query.label || "";

  $("tracks").innerHTML = "";
  for (const t of result.tracks) {
    const li = document.createElement("li");
    const info = document.createElement("div");
    const title = document.createElement("div");
    title.className = "track-title";
    title.textContent = `${t.artists.join(", ")} — ${t.name}`;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [t.year, t.descriptors.join(" · ")].filter(Boolean).join(" · ");
    info.append(title, meta);
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = t.score;
    li.append(info, score);
    $("tracks").append(li);
  }

  show($("more"), !(result.min_score <= 0 && result.tracks.length < result.limitPedido));
  if (!result.tracks.length) {
    $("notes").textContent += " — nada superó la exigencia. Bájala o amplía la búsqueda.";
  }
}

// Con una biblioteca sesgada, una petición alejada de su centro deja casi todo
// por debajo de la exigencia. En vez de dejar al usuario ajustando el número,
// se baja el listón por pasos sobre lo que ya hay en pantalla.
$("more").addEventListener("click", async (e) => {
  if (!current) return;
  setBusy(e.target, true, "Buscando…");
  const antes = current.tracks.length;
  try {
    const nextMin = Math.max(0, (current.min_score ?? 55) - 15);
    const nextLimit = antes + 10;
    const p = parametros();
    const r = await api("/api/more", {
      method: "POST",
      body: JSON.stringify({
        ...p,
        query: current.query,
        limit: nextLimit,
        target_minutes: null,
        min_score: nextMin,
        exclude: current.exclude || [],
      }),
    });
    current = { ...r, limitPedido: nextLimit, exclude: current.exclude, playlist: current.playlist, reference: current.reference };
    render(current);
    if (current.tracks.length === antes) {
      $("notes").textContent += " — no queda nada más que encaje en tu biblioteca.";
    }
  } catch (err) { alert(err.message); }
  finally { setBusy(e.target, false, "Ampliar la búsqueda"); }
});

/* ==================== escritura en Spotify ==================== */
$("save").addEventListener("click", async (e) => {
  if (!current || !current.tracks.length) return;
  setBusy(e.target, true, "Creando…");
  try {
    const r = await api("/api/save", {
      method: "POST",
      body: JSON.stringify({
        name: $("plname").value || current.query.label,
        description: (current.query.notes || "").slice(0, 300),
        track_ids: current.tracks.map((t) => t.id),
      }),
    });
    $("saved").innerHTML =
      `Creada con ${r.added} canciones · <a href="${r.url}" target="_blank" rel="noopener">abrir en Spotify</a>`;
  } catch (err) { alert(err.message); }
  finally { setBusy(e.target, false, "Crear en Spotify"); }
});

$("append").addEventListener("click", async (e) => {
  if (!current || !current.tracks.length || !current.playlist) return;
  setBusy(e.target, true, "Añadiendo…");
  try {
    const r = await api("/api/append", {
      method: "POST",
      body: JSON.stringify({
        playlist_id: current.playlist.id,
        track_ids: current.tracks.map((t) => t.id),
      }),
    });
    $("saved").innerHTML =
      `${r.added} canciones añadidas a «${current.playlist.name}» · ` +
      `<a href="${r.url}" target="_blank" rel="noopener">abrir en Spotify</a>`;
  } catch (err) { alert(err.message); }
  finally { setBusy(e.target, false, "Añadir a la lista"); }
});

pintarChips();
refreshStatus().catch((err) => { $("status").textContent = err.message; });
