/* Estado de sesión en la cabecera. Se carga en todas las páginas. */
window.CompasChrome = (async () => {
  const $ = (id) => document.getElementById(id);
  const show = (el, visible) => el && el.classList.toggle("hidden", !visible);

  let estado = { configured: false, connected: false };
  try {
    const res = await fetch("/api/status", { headers: { "Content-Type": "application/json" } });
    if (res.ok) estado = await res.json();
  } catch (err) {
    console.warn("No se pudo consultar el estado de la sesión", err);
  }

  const dentro = estado.configured && estado.connected;
  show($("login"), !dentro);
  show($("logout"), dentro);
  show($("whoami"), dentro);
  // En la propia aplicación el atajo sobra.
  show($("openapp"), dentro && location.pathname !== "/app");
  if (dentro) $("whoami").textContent = estado.user || "";

  const logout = $("logout");
  if (logout) {
    logout.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST" });
      location.href = "/";
    });
  }

  return estado;
})();
