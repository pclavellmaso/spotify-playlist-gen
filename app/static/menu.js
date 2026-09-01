/* Menú de navegación en móvil.
 *
 * Va en todas las páginas, incluida la web pública exportada: ahí no se cargan
 * los scripts que hablan con la API, pero este no la necesita.
 */
(() => {
  const burger = document.getElementById("burger");
  const panel = document.getElementById("navlinks");
  if (!burger || !panel) return;

  const cerrar = () => {
    burger.setAttribute("aria-expanded", "false");
    panel.classList.remove("is-open");
    document.removeEventListener("click", fuera, true);
    document.removeEventListener("keydown", escape);
  };
  const fuera = (e) => {
    if (!panel.contains(e.target) && !burger.contains(e.target)) cerrar();
  };
  const escape = (e) => { if (e.key === "Escape") cerrar(); };

  burger.addEventListener("click", () => {
    const abierto = burger.getAttribute("aria-expanded") === "true";
    if (abierto) return cerrar();
    burger.setAttribute("aria-expanded", "true");
    panel.classList.add("is-open");
    setTimeout(() => {
      document.addEventListener("click", fuera, true);
      document.addEventListener("keydown", escape);
    }, 0);
  });

  // Al elegir destino el panel sobra.
  panel.querySelectorAll("a").forEach((a) => a.addEventListener("click", cerrar));

  // En la pastilla no cabe la sesión entera, así que en móvil el cierre de
  // sesión vive aquí dentro. Se apoya en el botón real de la cabecera para no
  // duplicar la lógica.
  const salirMovil = document.getElementById("logout-movil");
  const salir = document.getElementById("logout");
  if (salirMovil && salir) {
    const sincronizar = () => { salirMovil.hidden = salir.classList.contains("hidden"); };
    salirMovil.addEventListener("click", () => salir.click());
    new MutationObserver(sincronizar).observe(salir, {
      attributes: true, attributeFilter: ["class"],
    });
    sincronizar();
  }
})();
