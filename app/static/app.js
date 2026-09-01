const $ = (id) => document.getElementById(id);
const show = (el, visible) => el && el.classList.toggle("hidden", !visible);

let current = null;   // última selección devuelta por la API
let modo = "new";     // "new" | "extend"
let yo = "";          // nombre de usuario, para no ofrecer listas ajenas

const MARCA = `<svg class="mark" viewBox="0 0 24 34" aria-hidden="true">
  <polygon class="f-nw" points="12,1 1,14 12,14"></polygon>
  <polygon class="f-ne" points="12,1 23,14 12,14"></polygon>
  <polygon class="f-sw" points="1,14 12,33 12,14"></polygon>
  <polygon class="f-se" points="23,14 12,33 12,14"></polygon>
</svg>`;

const EJEMPLOS = [
  "resaca de domingo con las persianas bajadas",
  "conduciendo de noche por la costa",
  "cocinando para gente que me cae bien",
  "última hora en una terraza que no quiere cerrar",
  "martes por la mañana, concentración y nada de voces",
  "calentando antes de salir de casa",
  "lluvia contra la ventana y ninguna prisa",
  "sobremesa que se alarga más de la cuenta",
  "kilómetro doce de una carrera larga",
  "bajando revoluciones antes de dormir",
  "primer café, sin hablar con nadie todavía",
  "sesión de tarde en una piscina vacía",
];

const NOMBRE_EJE = {
  energy: "energía", valence: "luminosidad", danceability: "baile",
  acousticness: "acústico", tempo_feel: "tempo", vocal_focus: "voz", warmth: "calidez",
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Error ${res.status}`);
  return body;
}

function ocupado(el, estado, etiqueta) {
  el.disabled = estado;
  if (etiqueta) el.textContent = etiqueta;
}

/* ==================== arranque ==================== */
(async () => {
  const estado = await window.CompasChrome;
  if (!estado.configured) {
    show($("gate"), true);
    $("gate-msg").textContent =
      "Todavía falta el Client ID de Spotify. Se rellena desde el navegador, sin tocar ficheros.";
    const ir = $("gate-login");
    ir.textContent = "Ir a los ajustes";
    ir.href = "/ajustes";
    return;
  }
  if (!estado.connected) { show($("gate"), true); return; }

  yo = estado.user || "";
  show($("studio"), true);
  // Sin Last.fm no hay grafo de similitud del que tirar.
  show($("explorar"), estado.discover);
  show($("descubrir"), estado.discover);
  pintarChips();
  await cargarListas();
  await refrescar();
})();

/* ==================== biblioteca ==================== */
const dialogo = $("libdialog");
$("libchip").addEventListener("click", () => dialogo.showModal());
$("libclose").addEventListener("click", () => dialogo.close());
dialogo.addEventListener("click", (e) => { if (e.target === dialogo) dialogo.close(); });

async function cargarListas() {
  if ($("source").options.length > 1) return;
  try {
    for (const p of await api("/api/playlists")) {
      const opt = document.createElement("option");
      opt.value = `playlist:${p.id}`;
      opt.textContent = `${p.name} · ${p.total}`;
      $("source").append(opt);

      // Sólo se puede escribir en las propias.
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

async function refrescar() {
  const s = await api(`/api/stats?source=${encodeURIComponent($("source").value)}`);

  // El indicador sólo insiste cuando queda trabajo por hacer.
  $("libstats").textContent = s.pending
    ? `${s.pending} canciones sin perfilar`
    : `${s.tagged} canciones perfiladas`;
  $("libdot").classList.toggle("libdot-pending", Boolean(s.pending));
  $("libchip").classList.toggle("libchip-quiet", !s.pending);
  $("libdetail").textContent =
    `${s.tagged} de ${s.total} perfiladas · ${s.pending} pendientes`;

  const job = s.job || {};
  const mia = job.source === $("source").value;
  const activo = job.running && mia;
  show($("progress"), activo);
  if (activo && job.total) {
    // El lote en curso todavía no cuenta: la barra se queda quieta mientras se
    // espera al modelo, y el rayado indica que sigue vivo.
    $("bar").style.width = `${Math.round((job.done / job.total) * 100)}%`;
    $("bar").classList.add("working");
    $("progtext").textContent =
      `Lote ${job.batch + 1} de ${job.batches} · ${job.done} de ${job.total}`;
    $("libstats").textContent = `Perfilando… ${job.done} de ${job.total}`;
    setTimeout(refrescar, 2500);
  } else {
    $("progtext").textContent = "";
  }

  const hecho = !job.running && mia && job.finished && job.done;
  show($("tagdone"), Boolean(hecho));
  if (hecho) $("tagdone").textContent = `${job.done} canciones perfiladas.`;

  $("taberror").textContent = job.error || "";
  show($("taberror"), Boolean(job.error));
  if (job.error && !dialogo.open) dialogo.showModal();
  return s;
}

$("source").addEventListener("change", refrescar);

$("sync").addEventListener("click", async (e) => {
  ocupado(e.target, true, "Sincronizando…");
  try {
    await api("/api/sync", { method: "POST", body: JSON.stringify({ source: $("source").value }) });
    await refrescar();
  } catch (err) { alert(err.message); }
  finally { ocupado(e.target, false, "Sincronizar"); }
});

$("tag").addEventListener("click", async (e) => {
  ocupado(e.target, true, "Lanzando…");
  show($("taberror"), false);
  show($("tagdone"), false);
  try {
    const r = await api("/api/tag", {
      method: "POST",
      body: JSON.stringify({ source: $("source").value, limit: Number($("taglimit").value) || null }),
    });
    if (!r.started) alert("No queda nada pendiente de perfilar en este origen.");
    await refrescar();
  } catch (err) { alert(err.message); }
  finally { ocupado(e.target, false, "Analizar"); }
});

/* ==================== modos ==================== */
function setModo(nuevo) {
  modo = nuevo;
  $("tab-new").classList.toggle("is-on", modo === "new");
  $("tab-extend").classList.toggle("is-on", modo === "extend");
  show($("extend-target"), modo === "extend");
  $("prompt").placeholder = modo === "extend"
    ? "Opcional: cómo quieres que varíe. «más tranquilo», «menos voces»…"
    : "Describe el momento…";
}
$("explorar").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-checked") !== "true";
  e.currentTarget.setAttribute("aria-checked", String(on));
});
const explorando = () => $("explorar").getAttribute("aria-checked") === "true";

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
    chip.addEventListener("click", () => { $("prompt").value = texto; $("prompt").focus(); });
    $("chips").append(chip);
  }
}

let iEjemplo = Math.floor(Math.random() * EJEMPLOS.length);
setInterval(() => {
  // Sólo mientras no haya nada escrito: rotar bajo los dedos sería molesto.
  if (modo !== "new" || $("prompt").value) return;
  iEjemplo = (iEjemplo + 1) % EJEMPLOS.length;
  $("prompt").placeholder = EJEMPLOS[iEjemplo];
}, 4200);

$("prompt").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = `${Math.min(e.target.scrollHeight, 190)}px`;
});
$("prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("generate").click(); }
});

/* ==================== conversación ==================== */
function burbuja(quien, contenido, clase = "") {
  const bienvenida = document.querySelector(".welcome");
  if (bienvenida) bienvenida.remove();

  const msg = document.createElement("div");
  msg.className = `msg msg-${quien}`;
  if (quien === "bot") {
    const av = document.createElement("span");
    av.className = "avatar";
    av.innerHTML = MARCA;
    msg.append(av);
  }
  const bubble = document.createElement("div");
  bubble.className = `bubble ${clase}`;
  if (typeof contenido === "string") bubble.textContent = contenido;
  else bubble.append(contenido);
  msg.append(bubble);
  $("chat").append(msg);
  msg.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return msg;
}

function interpretacion(result) {
  const cont = document.createElement("div");
  cont.append(Object.assign(document.createElement("div"), {
    textContent: result.query.notes || "Interpretado.",
  }));
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

/* ==================== parámetros ==================== */
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

/* ==================== generación ==================== */
$("generate").addEventListener("click", async (e) => {
  const prompt = $("prompt").value.trim();
  if (modo === "new" && !prompt) { $("prompt").focus(); return; }
  if (modo === "extend" && !$("target").value) { alert("Elige la lista que quieres ampliar."); return; }

  const nombreLista = modo === "extend"
    ? $("target").selectedOptions[0].textContent.split(" · ")[0] : "";
  burbuja("you", modo === "extend"
    ? `Más como «${nombreLista}»${prompt ? `, pero ${prompt}` : ""}`
    : prompt);
  const pensando = burbuja("bot", "Interpretando…", "typing");

  ocupado(e.currentTarget, true);
  try {
    const p = parametros();
    const r = modo === "extend"
      ? await api("/api/extend", {
          method: "POST",
          body: JSON.stringify({ ...p, playlist_id: $("target").value, prompt }),
        })
      : await api("/api/generate", { method: "POST", body: JSON.stringify({ ...p, prompt }) });

    r.limitPedido = p.limit;
    current = r;
    pensando.remove();
    burbuja("bot", interpretacion(r));
    mostrarResultado(r);
    $("prompt").value = "";
    $("prompt").style.height = "auto";
    if (explorando()) await explorarFuera();
  } catch (err) {
    pensando.remove();
    burbuja("bot", err.message);
  } finally {
    ocupado(e.currentTarget, false);
  }
});

/* ==================== resultado, a solas ==================== */
// Con la lista delante, el hilo y el redactor sólo compiten por la atención.
// Se aparta todo y se vuelve con el botón.
function verChat() {
  show($("chatview"), true);
  show($("resultview"), false);
  show($("libchip"), true);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
  $("prompt").focus();
}
$("back").addEventListener("click", verChat);

function mostrarResultado(result) {
  show($("chatview"), false);
  show($("libchip"), false);
  show($("resultview"), true);
  $("saved").textContent = "";

  $("rv-name").textContent = result.query.label || "Selección";
  const partes = [
    `${result.tracks.length} de ${result.pool}`,
    `${result.minutes} min`,
    `exigencia ${result.min_score}`,
  ];
  if (result.reference) partes.push(`referencia ${result.reference}`);
  if (result.descubiertas) partes.push(`${result.descubiertas} de fuera`);
  $("rv-meta").textContent = partes.join(" · ");
  $("rv-notes").textContent = result.query.notes || "";

  const ampliando = Boolean(result.playlist);
  show($("namefield"), !ampliando);
  show($("save"), !ampliando);
  show($("append"), ampliando);
  if (ampliando) $("append").textContent = `Añadir a «${result.playlist.name}»`;
  else $("plname").value = result.query.label || "";

  $("tracks").innerHTML = "";
  for (const t of result.tracks) {
    const li = document.createElement("li");
    if (t.nueva) li.classList.add("nueva");
    const info = document.createElement("div");
    const titulo = document.createElement("div");
    titulo.className = "track-title";
    titulo.textContent = `${t.artists.join(", ")} — ${t.name}`;
    const meta = document.createElement("div");
    meta.className = "track-meta";
    meta.textContent = [t.year, t.descriptors.join(" · ")].filter(Boolean).join(" · ");
    info.append(titulo, meta);
    const nota = document.createElement("span");
    nota.className = "score";
    nota.textContent = t.score;
    li.append(info, nota);
    $("tracks").append(li);
  }

  if (!result.tracks.length) {
    $("rv-notes").textContent += " — nada superó la exigencia. Bájala o amplía la búsqueda.";
  }
  show($("more"), !(result.min_score <= 0 && result.tracks.length < result.limitPedido));
  window.scrollTo({ top: 0, behavior: "instant" });
}

// Con una biblioteca sesgada, una petición alejada de su centro deja casi todo
// por debajo de la exigencia. En vez de dejar al usuario ajustando el número a
// mano, se baja el listón por pasos sobre lo que ya hay en pantalla.
$("more").addEventListener("click", async (e) => {
  if (!current) return;
  ocupado(e.target, true, "Buscando…");
  const antes = current.tracks.length;
  const cuantas = Number($("morecount").value) || 10;
  try {
    const r = await api("/api/more", {
      method: "POST",
      body: JSON.stringify({
        ...parametros(),
        query: current.query,
        limit: antes + cuantas,
        target_minutes: null,
        min_score: Math.max(0, (current.min_score ?? 55) - 15),
        exclude: current.exclude || [],
      }),
    });
    current = { ...r, limitPedido: antes + cuantas, exclude: current.exclude,
                playlist: current.playlist, reference: current.reference };
    mostrarResultado(current);
    if (current.tracks.length === antes) {
      $("saved").textContent = "No queda nada más en tu biblioteca que encaje con esto.";
    }
  } catch (err) { alert(err.message); }
  finally { ocupado(e.target, false, "Ampliar"); }
});

/* ==================== explorar fuera de la biblioteca ==================== */
// Spotify retiró /recommendations en 2024, así que los parecidos salen del
// grafo de Last.fm partiendo de los artistas que YA han encajado. Todo lo que
// vuelve pasa por el mismo scorer: el criterio no se relaja por venir de fuera.
async function explorarFuera(boton) {
  if (!current || !current.tracks.length) return;
  const semillas = [...new Set(current.tracks.map((t) => t.artists[0]).filter(Boolean))];
  const aviso = burbuja("bot", "Buscando fuera de tu biblioteca… tarda un minuto largo.", "typing");
  if (boton) ocupado(boton, true, "Buscando…");
  try {
    const r = await api("/api/discover", {
      method: "POST",
      body: JSON.stringify({
        ...parametros(),
        query: current.query,
        seeds: semillas,
        exclude: current.tracks.map((t) => t.id),
      }),
    });
    aviso.remove();
    if (!r.tracks.length) {
      burbuja("bot", `Se han mirado ${r.candidatos} temas nuevos y ninguno supera tu nota.`);
      return;
    }
    // Se funden en una sola lista, marcando lo que no es tuyo.
    const nuevas = r.tracks.map((t) => ({ ...t, nueva: true }));
    current = {
      ...current,
      tracks: [...current.tracks, ...nuevas].sort((a, b) => b.score - a.score),
      minutes: current.minutes + r.minutes,
      descubiertas: nuevas.length,
    };
    mostrarResultado(current);
  } catch (err) {
    aviso.remove();
    burbuja("bot", err.message);
  } finally {
    if (boton) ocupado(boton, false, "Explorar fuera");
  }
}

$("descubrir").addEventListener("click", (e) => explorarFuera(e.currentTarget));

/* ==================== escritura en Spotify ==================== */
$("save").addEventListener("click", async (e) => {
  if (!current || !current.tracks.length) return;
  ocupado(e.target, true, "Creando…");
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
  finally { ocupado(e.target, false, "Crear en Spotify"); }
});

$("append").addEventListener("click", async (e) => {
  if (!current || !current.tracks.length || !current.playlist) return;
  ocupado(e.target, true, "Añadiendo…");
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
  finally { ocupado(e.target, false, `Añadir a «${current.playlist.name}»`); }
});
