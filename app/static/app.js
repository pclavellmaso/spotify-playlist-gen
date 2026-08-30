const $ = (id) => document.getElementById(id);
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

async function refreshStatus() {
  const s = await api("/api/status");
  if (!s.configured) {
    $("status").innerHTML = "Falta <code>SPOTIFY_CLIENT_ID</code> en tu <code>.env</code>.";
    return;
  }
  if (!s.connected) {
    $("status").innerHTML = '<a href="/api/auth/login">Conectar con Spotify →</a>';
    return;
  }
  $("status").textContent = `Conectado como ${s.user} · modelo ${s.model}`;
  $("setup").classList.remove("hidden");
  $("generator").classList.remove("hidden");
  await loadPlaylists();
  await refreshStats();
}

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
  const active = job.running && job.source === $("source").value;
  $("progress").classList.toggle("hidden", !active);
  if (active && job.total) {
    $("bar").style.width = `${Math.round((job.done / job.total) * 100)}%`;
    setTimeout(refreshStats, 2500);
  }
  if (job.error) $("libstats").textContent += ` · error: ${job.error}`;
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
  try {
    const r = await api("/api/tag", {
      method: "POST",
      body: JSON.stringify({ source: $("source").value }),
    });
    if (!r.started) alert("No hay nada pendiente de analizar.");
    await refreshStats();
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Analizar pendientes");
  }
});

$("generate").addEventListener("click", async (e) => {
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  setBusy(e.target, true, "Pensando…");
  try {
    current = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        source: $("source").value,
        limit: Number($("limit").value),
        min_score: Number($("minscore").value),
        max_per_artist: Number($("maxartist").value),
      }),
    });
    render(current);
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Generar");
  }
});

function render(result) {
  $("results").classList.remove("hidden");
  $("saved").textContent = "";
  $("reslabel").textContent = result.query.label || "Seleccion";
  $("notes").textContent =
    `${result.tracks.length} de ${result.pool} analizadas · ${result.query.notes}`;
  $("plname").value = result.query.label || "";

  $("tracks").innerHTML = "";
  for (const t of result.tracks) {
    const li = document.createElement("li");
    const title = document.createElement("div");
    title.textContent = `${t.artists.join(", ")} — ${t.name}`;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = t.score;
    title.prepend(score);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [t.year, t.descriptors.join(" · ")].filter(Boolean).join(" · ");
    li.append(title, meta);
    $("tracks").append(li);
  }
  if (!result.tracks.length) {
    $("notes").textContent += " — nada supero la nota minima, prueba a bajarla.";
  }
}

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
    $("saved").innerHTML = `Guardada: <a href="${r.url}" target="_blank" rel="noopener">abrir en Spotify</a>`;
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Guardar en Spotify");
  }
});

refreshStatus().catch((err) => {
  $("status").textContent = err.message;
});
