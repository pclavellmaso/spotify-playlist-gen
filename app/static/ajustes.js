const $ = (id) => document.getElementById(id);

const SIN_CLAVE = new Set(["ollama", "lmstudio"]);
let porDefecto = {};

async function cargar() {
  const c = await (await fetch("/api/config")).json();
  porDefecto = c.modelos_por_defecto || {};

  $("spotify_client_id").placeholder = c.spotify_client_id
    ? "Ya configurado — déjalo en blanco para no cambiarlo"
    : "32 caracteres hexadecimales";
  $("ai_provider").value = c.ai_provider || "anthropic";
  $("ai_model").value = c.ai_model || "";
  $("ai_base_url").value = c.ai_base_url || "";
  $("redirect").textContent = c.redirect_uri;

  marcar("st-spotify", Boolean(c.spotify_client_id));
  marcar("st-ai", c.ai_api_key_set);
  marcar("st-lastfm", c.lastfm_api_key_set);
  if (c.ai_api_key_set) $("ai_api_key").placeholder = "Ya configurada — en blanco para no cambiarla";
  if (c.lastfm_api_key_set) $("lastfm_api_key").placeholder = "Ya configurada — en blanco para no cambiarla";
  ajustarProveedor();
}

function marcar(id, puesto) {
  const el = $(id);
  el.textContent = puesto ? "configurado" : "sin configurar";
  el.classList.toggle("tick-on", puesto);
}

// Un modelo local no lleva clave: enseñar el campo sólo confunde.
function ajustarProveedor() {
  const p = $("ai_provider").value;
  $("key-field").classList.toggle("hidden", SIN_CLAVE.has(p));
  $("ai_model").placeholder = porDefecto[p] || "";
}
$("ai_provider").addEventListener("change", ajustarProveedor);

$("guardar").addEventListener("click", async (e) => {
  const campos = ["spotify_client_id", "ai_provider", "ai_model", "ai_api_key",
                  "ai_base_url", "lastfm_api_key"];
  const cuerpo = {};
  for (const campo of campos) {
    const v = $(campo).value.trim();
    if (v) cuerpo[campo] = v;
  }
  if (!Object.keys(cuerpo).length) {
    $("conf-msg").textContent = "No has rellenado nada que guardar.";
    return;
  }

  e.target.disabled = true;
  e.target.textContent = "Guardando…";
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "No se pudo guardar");

    $("conf-msg").textContent = "Guardado. Reiniciando para aplicar los cambios…";
    // Las claves se leen al arrancar, así que el proceso se reinicia solo. El
    // lanzador lo vuelve a levantar; aquí sólo hay que esperar a que responda.
    await fetch("/api/restart", { method: "POST" });
    esperarYVolver();
  } catch (err) {
    $("conf-msg").textContent = err.message;
    e.target.disabled = false;
    e.target.textContent = "Guardar y reiniciar";
  }
});

async function esperarYVolver(intentos = 40) {
  for (let i = 0; i < intentos; i++) {
    await new Promise((r) => setTimeout(r, 700));
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      if (res.ok) { location.href = "/app"; return; }
    } catch { /* todavía levantándose */ }
  }
  $("conf-msg").innerHTML =
    "Guardado, pero el servidor no ha vuelto solo. Si lo arrancaste a mano, " +
    "vuelve a ejecutarlo; con el lanzador se reinicia solo.";
}

cargar().catch((err) => { $("conf-msg").textContent = err.message; });
