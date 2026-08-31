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
  // El nombre viene de Spotify, asi que no se mete por innerHTML.
  const status = $("status");
  status.textContent = `Conectado como ${s.user} · modelo ${s.model} · `;
  const fm = document.createElement("span");
  if (s.lastfm) {
    fm.textContent = "Last.fm activo";
  } else {
    fm.innerHTML =
      "sin Last.fm — a\u00f1ade <code>LASTFM_API_KEY</code> al .env para afinar el cat\u00e1logo que el modelo no conoce";
  }
  status.append(fm);
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
  const mine = job.source === $("source").value;
  const active = job.running && mine;
  $("progress").classList.toggle("hidden", !active);
  if (active && job.total) {
    // El lote en curso aun no cuenta, asi que la barra se queda quieta
    // mientras se espera al modelo: el rayado indica que sigue vivo.
    $("bar").style.width = `${Math.round((job.done / job.total) * 100)}%`;
    $("bar").classList.add("working");
    $("progtext").textContent =
      `Lote ${job.batch + 1} de ${job.batches} · ${job.done} de ${job.total} canciones analizadas`;
    setTimeout(refreshStats, 2500);
  }

  const donemsg = !job.running && mine && job.finished && job.done;
  $("tagdone").classList.toggle("hidden", !donemsg);
  if (donemsg) {
    $("tagdone").textContent =
      `Listo: ${job.done} canciones analizadas. Ya puedes describir un momento aqui debajo.`;
  }
  $("taberror").textContent = job.error || "";
  $("taberror").classList.toggle("hidden", !job.error);
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
  $("taberror").classList.add("hidden");
  $("tagdone").classList.add("hidden");
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
    `${result.tracks.length} de ${result.pool} analizadas · nota minima ${result.min_score}`
    + ` · ${result.query.notes}`;
  // No se pisa un nombre que ya haya escrito el usuario al ampliar la lista.
  if (!$("plname").value) $("plname").value = result.query.label || "";
  $("more").classList.toggle("hidden", result.min_score <= 0
    && result.tracks.length < result.limitPedido);

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

// Con una biblioteca sesgada -toda musica de baile, por ejemplo- una peticion
// muy alejada de su centro deja casi todo por debajo de la nota minima. En vez
// de dejar al usuario ajustando el numero a mano, se baja el liston por pasos.
$("more").addEventListener("click", async (e) => {
  if (!current) return;
  setBusy(e.target, true, "Buscando…");
  const antes = current.tracks.length;
  try {
    const nextMin = Math.max(0, (current.min_score ?? 55) - 15);
    const nextLimit = (current.limit || antes) + 10;
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
      $("notes").textContent +=
        " — no hay mas canciones que encajen en tu biblioteca.";
    }
  } catch (err) {
    alert(err.message);
  } finally {
    setBusy(e.target, false, "Anadir 10 mas");
  }
});

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
