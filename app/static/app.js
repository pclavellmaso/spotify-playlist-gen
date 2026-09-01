const $ = (id) => document.getElementById(id);
const show = (el, visible) => el && el.classList.toggle("hidden", !visible);

let current = null;   // última selección devuelta por la API
let modo = "new";     // "new" | "extend"
let yo = "";          // nombre de usuario, para no ofrecer listas ajenas

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

/* ==================== arranque ==================== */
(async () => {
  const estado = await window.CompasChrome;
  if (!estado.configured) {
    show($("gate"), true);
    $("gate-msg").innerHTML =
      "Todavía falta el Client ID de Spotify. Se rellena desde el navegador, " +
      "sin tocar ningún fichero.";
    const ir = $("gate-login");
    ir.textContent = "Ir a los ajustes";
    ir.href = "/ajustes";
    return;
  }
  if (!estado.connected) {
    show($("gate"), true);
    return;
  }

  yo = estado.user || "";
  show($("studio"), true);
  pintarChips();
  await cargarListas();
  await refrescar();
})();

/* ==================== biblioteca ==================== */
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
  $("libstats").textContent =
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
      `Lote ${job.batch + 1} de ${job.batches} · ${job.done} de ${job.total} perfiladas`;
    $("libpanel").open = true;
    setTimeout(refrescar, 2500);
  } else {
    $("progtext").textContent = "";
  }

  const hecho = !job.running && mia && job.finished && job.done;
  show($("tagdone"), Boolean(hecho));
  if (hecho) $("tagdone").textContent = `${job.done} canciones perfiladas.`;

  $("taberror").textContent = job.error || "";
  show($("taberror"), Boolean(job.error));
  if (job.error) $("libpanel").open = true;
  return s;
}

$("source").addEventListener("change", refrescar);

function ocupado(el, estado, etiqueta) {
  el.disabled = estado;
  if (etiqueta) el.textContent = etiqueta;
}

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
  $("prompt").placeholder =
    modo === "extend"
      ? "Opcional: cómo quieres que varíe. «más tranquilo», «menos voces»…"
      : "Describe el momento…";
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

/* El campo crece con el texto, como cualquier redactor decente. */
$("prompt").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = `${Math.min(e.target.scrollHeight, 190)}px`;
});
$("prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("generate").click(); }
});

/* ==================== conversación ==================== */
function limpiarBienvenida() {
  const w = document.querySelector(".welcome");
  if (w) w.remove();
}

function burbuja(quien, contenido, clase = "") {
  limpiarBienvenida();
  const msg = document.createElement("div");
  msg.className = `msg msg-${quien}`;
  if (quien === "bot") {
    const av = document.createElement("span");
    av.className = "avatar";
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
    pintarResultado(r);
    $("prompt").value = "";
    $("prompt").style.height = "auto";
  } catch (err) {
    pensando.remove();
    burbuja("bot", err.message);
  } finally {
    ocupado(e.currentTarget, false);
  }
});

/* ==================== resultado ==================== */
function pintarResultado(result) {
  // Sólo el último bloque conserva acciones: dejar botones vivos en respuestas
  // antiguas invita a guardar una selección que ya no es la que se ve.
  document.querySelectorAll(".result-actions, .saved").forEach((el) => el.remove());

  const caja = document.createElement("section");
  caja.className = "result";

  const head = document.createElement("div");
  head.className = "result-head";
  head.innerHTML =
    `<h3></h3><span class="result-meta"></span>`;
  head.querySelector("h3").textContent = result.query.label || "Selección";
  const partes = [
    `${result.tracks.length} de ${result.pool}`,
    `${result.minutes} min`,
    `exigencia ${result.min_score}`,
  ];
  if (result.reference) partes.push(`referencia ${result.reference}`);
  head.querySelector(".result-meta").textContent = partes.join(" · ");
  caja.append(head);

  const lista = document.createElement("ol");
  lista.className = "tracks";
  for (const t of result.tracks) {
    const li = document.createElement("li");
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
    lista.append(li);
  }
  caja.append(lista);

  if (!result.tracks.length) {
    const vacio = document.createElement("p");
    vacio.className = "hint";
    vacio.style.padding = "0 20px 16px";
    vacio.textContent = "Nada superó la exigencia. Bájala o amplía la búsqueda.";
    caja.append(vacio);
  }

  caja.append(acciones(result));
  const guardado = document.createElement("p");
  guardado.className = "saved";
  caja.append(guardado);

  const msg = document.createElement("div");
  msg.className = "msg msg-bot";
  msg.append(Object.assign(document.createElement("span"), { className: "avatar" }), caja);
  $("chat").append(msg);
  msg.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function acciones(result) {
  const barra = document.createElement("div");
  barra.className = "result-actions";

  const mas = document.createElement("button");
  mas.className = "btn btn-flat btn-sm";
  mas.textContent = "Ampliar la búsqueda";
  show(mas, !(result.min_score <= 0 && result.tracks.length < result.limitPedido));
  mas.addEventListener("click", () => ampliar(mas));
  barra.append(mas);

  if (result.playlist) {
    const anadir = document.createElement("button");
    anadir.className = "btn btn-primary btn-sm";
    anadir.textContent = `Añadir a «${result.playlist.name}»`;
    anadir.addEventListener("click", () => anadirALista(anadir, barra));
    barra.append(anadir);
  } else {
    const nombre = document.createElement("input");
    nombre.id = "plname";
    nombre.placeholder = "Nombre de la playlist";
    nombre.value = result.query.label || "";
    const crear = document.createElement("button");
    crear.className = "btn btn-primary btn-sm";
    crear.textContent = "Crear en Spotify";
    crear.addEventListener("click", () => crearLista(crear, nombre, barra));
    barra.append(nombre, crear);
  }
  return barra;
}

function avisar(barra, html) {
  const p = barra.parentElement.querySelector(".saved");
  if (p) p.innerHTML = html;
}

// Con una biblioteca sesgada, una petición alejada de su centro deja casi todo
// por debajo de la exigencia. En vez de dejar al usuario ajustando el número a
// mano, se baja el listón por pasos sobre lo que ya hay en pantalla.
async function ampliar(boton) {
  if (!current) return;
  ocupado(boton, true, "Buscando…");
  const antes = current.tracks.length;
  try {
    const r = await api("/api/more", {
      method: "POST",
      body: JSON.stringify({
        ...parametros(),
        query: current.query,
        limit: antes + 10,
        target_minutes: null,
        min_score: Math.max(0, (current.min_score ?? 55) - 15),
        exclude: current.exclude || [],
      }),
    });
    current = { ...r, limitPedido: antes + 10, exclude: current.exclude, playlist: current.playlist, reference: current.reference };
    pintarResultado(current);
    if (current.tracks.length === antes) {
      burbuja("bot", "No queda nada más en tu biblioteca que encaje con esto.");
    }
  } catch (err) { alert(err.message); }
  finally { ocupado(boton, false, "Ampliar la búsqueda"); }
}

async function crearLista(boton, campoNombre, barra) {
  if (!current || !current.tracks.length) return;
  ocupado(boton, true, "Creando…");
  try {
    const r = await api("/api/save", {
      method: "POST",
      body: JSON.stringify({
        name: campoNombre.value || current.query.label,
        description: (current.query.notes || "").slice(0, 300),
        track_ids: current.tracks.map((t) => t.id),
      }),
    });
    avisar(barra, `Creada con ${r.added} canciones · <a href="${r.url}" target="_blank" rel="noopener">abrir en Spotify</a>`);
  } catch (err) { alert(err.message); }
  finally { ocupado(boton, false, "Crear en Spotify"); }
}

async function anadirALista(boton, barra) {
  if (!current || !current.tracks.length || !current.playlist) return;
  ocupado(boton, true, "Añadiendo…");
  try {
    const r = await api("/api/append", {
      method: "POST",
      body: JSON.stringify({
        playlist_id: current.playlist.id,
        track_ids: current.tracks.map((t) => t.id),
      }),
    });
    avisar(barra, `${r.added} canciones añadidas a «${current.playlist.name}» · <a href="${r.url}" target="_blank" rel="noopener">abrir en Spotify</a>`);
  } catch (err) { alert(err.message); }
  finally { ocupado(boton, false, `Añadir a «${current.playlist.name}»`); }
}
