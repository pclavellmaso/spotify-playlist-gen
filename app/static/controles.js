/* Desplegables y contadores con forma propia.
 *
 * Los nativos no se pueden maquetar: el navegador dibuja la lista con su
 * propio estilo y no hay CSS que lo cambie. Se sustituyen por un botón y un
 * menú propios, pero **el <select> original se queda en el DOM**, oculto y
 * sincronizado: así todo el código que hace `sel.value`, `selectedOptions` o
 * escucha `change` sigue funcionando sin enterarse.
 */
(() => {
  const CHEVRON = `<svg viewBox="0 0 12 8" aria-hidden="true"><path d="M1 1.5 6 6.5 11 1.5"/></svg>`;

  function montarSelect(select) {
    if (select.dataset.montado) return;
    select.dataset.montado = "1";

    const caja = document.createElement("div");
    caja.className = "dd";
    if (select.classList.contains("sel-bare")) caja.classList.add("dd-bare");

    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "dd-btn";
    boton.innerHTML = `<span class="dd-label"></span>${CHEVRON}`;

    const menu = document.createElement("div");
    menu.className = "dd-menu";
    menu.setAttribute("role", "listbox");

    select.after(caja);
    caja.append(select, boton, menu);
    select.classList.add("dd-native");

    const pintar = () => {
      boton.querySelector(".dd-label").textContent =
        select.selectedOptions[0]?.textContent ?? "";
      menu.innerHTML = "";
      for (const opt of select.options) {
        const fila = document.createElement("button");
        fila.type = "button";
        fila.className = "dd-opt" + (opt.selected ? " is-on" : "");
        fila.textContent = opt.textContent;
        fila.addEventListener("click", () => {
          select.value = opt.value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          cerrar();
          pintar();
        });
        menu.append(fila);
      }
    };

    const cerrar = () => {
      caja.classList.remove("is-open");
      document.removeEventListener("click", fuera, true);
    };
    const fuera = (e) => { if (!caja.contains(e.target)) cerrar(); };

    boton.addEventListener("click", () => {
      const abierto = caja.classList.toggle("is-open");
      // Sólo un menú abierto a la vez.
      document.querySelectorAll(".dd.is-open").forEach((o) => o !== caja && o.classList.remove("is-open"));
      if (!abierto) return;
      // El redactor vive pegado al fondo: ahí abajo no cabe nada.
      const hueco = window.innerHeight - boton.getBoundingClientRect().bottom;
      caja.classList.toggle("dd-arriba", hueco < Math.min(menu.scrollHeight + 20, 300));
      setTimeout(() => document.addEventListener("click", fuera, true), 0);
    });

    // Las playlists se cargan después: el menú se rehace cuando cambian.
    new MutationObserver(pintar).observe(select, { childList: true });
    select.addEventListener("change", pintar);
    pintar();
  }

  function montarNumero(input) {
    if (input.dataset.montado) return;
    input.dataset.montado = "1";

    const caja = document.createElement("div");
    caja.className = "num";
    input.after(caja);
    caja.append(input);

    const paso = (delta) => {
      const min = input.min === "" ? -Infinity : Number(input.min);
      const max = input.max === "" ? Infinity : Number(input.max);
      const actual = Number(input.value) || 0;
      input.value = Math.min(max, Math.max(min, actual + delta));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };

    const flechas = document.createElement("div");
    flechas.className = "num-arrows";
    for (const [clase, delta] of [["up", 1], ["down", -1]]) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `num-${clase}`;
      b.tabIndex = -1;
      b.innerHTML = CHEVRON;
      b.addEventListener("click", () => paso(delta));
      flechas.append(b);
    }
    caja.append(flechas);
  }

  function montarTodo() {
    document.querySelectorAll("select").forEach(montarSelect);
    document.querySelectorAll('input[type="number"]').forEach(montarNumero);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", montarTodo);
  } else {
    montarTodo();
  }
  window.CompasControles = montarTodo;
})();
