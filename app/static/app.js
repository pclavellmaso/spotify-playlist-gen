const $ = (id) => document.getElementById(id);
const show = (el, visible) => el.classList.toggle("hidden", !visible);
let current = null;

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

/* ---------------- sesión ---------------- */
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
    setLoggedOut(
      "Falta <code>SPOTIFY_CLIENT_ID</code> en tu <code>.env</code>. " +
        "Mira los pasos de aquí abajo."
    );
    return;
  }
  if (!s.connected) {
    setLoggedOut("Listo para conectar. Se abrirá Spotify para que autorices el acceso.");
    return;
  }

  // Conectado: la landing estorba, se muestra la aplicación.
  show($("landing"), false);
  document.querySelectorAll(".landing-only").forEach((el) => show(el, false));
  show($("login"), false);
  show($("logout"), true);
  show($("whoami"), true);
  $("whoami").textContent = s.user;
  show($("setup"), true);
  show($("generator"), true);

  const fm = s.lastfm ? "Last.fm activo" : "sin Last.fm";
  $("status").textContent = `Conectado · modelo ${s.model} · ${fm}`;

  await loadPlaylists();
  await refreshStats();
}

$("logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.href = "/";
});

/* ---------------- biblioteca ---------------- */
async function loadPlaylists() {
  const select = $("source");
  if (select.options.length > 1) return;
  try {
    const lists = await api("/api/playlists");
    for (const p of lists) {
      const opt = document.createElement("option");
      opt.value = `playlist:${p.id}`;
      opt.textContent = `${p.name} (${p.total})`;
      select.append(opt);
    }
  } catch (err) {
    console.warn("No se pudieron cargar las playlists", err);
  }
}

async function refreshStats() {
  const s = await api(`/api/stats?source=${encodeURIComponent($("source").value)}`);
  $("libstats").textContent =
    `${s.total} canciones sincronizadas · ${s.tagged} analizadas · ${s.pending} pendientes`;

  const job = s.job || {};
  const mine = job.source === $("source").value;
  const active = job.running && mine;
  show($("progress"), active);
  if (active && job.total) {
    // El lote en curso aún no cuenta, así que la barra se queda quieta
    // mientras se espera al modelo: el rayado indica que sigue vivo.
    $("bar").style.width = `${Math.round((job.done / job.total) * 100)}%`;
    $("bar").classList.add("working");
    $("progtext").textContent =
      `Lote ${job.batch + 1} de ${job.batches} · ${job.done} de ${job.total} canciones analizadas`;
    setTimeout(refreshStats, 2500);
  } else {
    $("progtext").textContent = "";
  }

  const donemsg = !job.running && mine && job.finished && job.done;
  show($("tagdone"), Boolean(donemsg));
  if (donemsg) {
    $("tagdone").textContent =
      `Listo: ${job.done} canciones analizadas. Ya puedes describir un momento aquí debajo.`;
  }

  $("taberror").textContent = job.error || "";
  show($("taberror"), Boolean(job.error));
  return s;
}

$("source").addEventListener("change", refreshStats);

$("sync").addEventListener("click", async (e) => {
  setBusy(e.target, true, "Sincronizando…");
  try {
    await api("/api/sync", {
      method: "POST",
      body: JSON.stringify({ source: $("source").value }),
    });
    await refreshStats();
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Sincronizar");
  }
});

$("tag").addEventListener("click", async (e) => {
  setBusy(e.target, true, "Lanzando…");
  show($("taberror"), false);
  show($("tagdone"), false);
  try {
    const r = await api("/api/tag", {
      method: "POST",
      body: JSON.stringify({
        source: $("source").value,
        limit: Number($("taglimit").value) || null,
      }),
    });
    if (!r.started) alert("No hay nada pendiente de analizar.");
    await refreshStats();
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Analizar pendientes");
  }
});

/* ---------------- generación ---------------- */
$("generate").addEventListener("click", async (e) => {
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  setBusy(e.target, true, "Pensando…");
  try {
    const limit = Number($("limit").value);
    current = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        source: $("source").value,
        limit,
        min_score: Number($("minscore").value),
        max_per_artist: Number($("maxartist").value),
      }),
    });
    current.limit = limit;
    current.limitPedido = limit;
    $("plname").value = "";
    render(current);
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Generar");
  }
});

function render(result) {
  show($("results"), true);
  $("saved").textContent = "";
  $("reslabel").textContent = result.query.label || "Selección";
  $("notes").textContent =
    `${result.tracks.length} de ${result.pool} analizadas · nota mínima ${result.min_score}`
    + ` · ${result.query.notes}`;
  // No se pisa un nombre que ya haya escrito el usuario al ampliar la lista.
  if (!$("plname").value) $("plname").value = result.query.label || "";

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
    $("notes").textContent += " — nada superó la nota mínima. Prueba a bajarla o a añadir más.";
  }
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Con una biblioteca sesgada -toda música de baile, por ejemplo- una petición
// muy alejada de su centro deja casi todo por debajo de la nota mínima. En vez
// de dejar al usuario ajustando el número a mano, se baja el listón por pasos.
$("more").addEventListener("click", async (e) => {
  if (!current) return;
  setBusy(e.target, true, "Buscando…");
  const antes = current.tracks.length;
  try {
    // Sobre las que hay en pantalla, no sobre el tope configurado: si el tope
    // era 30 y solo pasaban 3, subirlo a 40 dejaba entrar 40 de golpe.
    const nextMin = Math.max(0, (current.min_score ?? 55) - 15);
    const nextLimit = antes + 10;
    const r = await api("/api/more", {
      method: "POST",
      body: JSON.stringify({
        query: current.query,
        source: $("source").value,
        limit: nextLimit,
        min_score: nextMin,
        max_per_artist: Number($("maxartist").value),
      }),
    });
    current = { ...r, limit: nextLimit, limitPedido: nextLimit };
    render(current);
    if (current.tracks.length === antes) {
      $("notes").textContent += " — no hay más canciones que encajen en tu biblioteca.";
    }
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Añadir 10 más");
  }
});

/* ---------------- guardar ---------------- */
$("save").addEventListener("click", async (e) => {
  if (!current || !current.tracks.length) return;
  setBusy(e.target, true, "Guardando…");
  try {
    const r = await api("/api/save", {
      method: "POST",
      body: JSON.stringify({
        name: $("plname").value || current.query.label,
        description: current.query.notes.slice(0, 300),
        track_ids: current.tracks.map((t) => t.id),
      }),
    });
    $("saved").innerHTML =
      `Guardada con ${r.added} canciones · <a href="${r.url}" target="_blank" rel="noopener">abrir en Spotify</a>`;
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Guardar en Spotify");
  }
});

refreshStatus().catch((err) => {
  $("status").textContent = err.message;
});
