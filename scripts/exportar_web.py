"""Exporta las paginas publicas a HTML estatico, listo para GitHub Pages.

Solo salen portada, metodo y guia: no llevan estado ni secretos, asi que se
pueden servir desde cualquier sitio. La aplicacion se queda en local, que es
donde tiene sentido -necesita tu sesion de Spotify, tu clave del modelo y un
disco donde guardar el perfilado-.

    python scripts/exportar_web.py

Deja el resultado en docs/. Para publicarlo: Settings -> Pages -> Source:
"Deploy from a branch", rama main, carpeta /docs.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from jinja2 import Environment, FileSystemLoader  # noqa: E402

SALIDA = RAIZ / "docs"
PAGINAS = {"index.html": "inicio", "metodo.html": "metodo", "guia.html": "guia"}
REPO = "https://github.com/pclavellmaso/spotify-playlist-gen"

# GitHub Pages sirve bajo /<repo>/, asi que las rutas absolutas no valen. Y las
# de la aplicacion no existen aqui: apuntan a la guia, que es lo que puede
# hacer quien llega desde fuera.
RUTAS = [
    (r'href="/static/', 'href="static/'),
    (r'src="/static/', 'src="static/'),
    (r'href="/metodo"', 'href="metodo.html"'),
    (r'href="/metodo#', 'href="metodo.html#'),
    (r'href="/guia"', 'href="guia.html"'),
    (r'href="/guia#', 'href="guia.html#'),
    (r'href="/app"', 'href="guia.html"'),
    (r'href="/ajustes"', 'href="guia.html#instalar"'),
    (r'href="/docs"', f'href="{REPO}"'),
    (r'href="/"', 'href="index.html"'),
]


def exportar() -> None:
    entorno = Environment(
        loader=FileSystemLoader(RAIZ / "app" / "templates"), autoescape=True
    )

    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    SALIDA.mkdir()

    for fichero, nombre in PAGINAS.items():
        html = entorno.get_template(fichero).render(page=nombre, estatico=True)
        for patron, reemplazo in RUTAS:
            html = re.sub(patron, reemplazo, html)
        (SALIDA / fichero).write_text(html)
        print(f"  {fichero}")

    # Estilos y favicon: los scripts hablan con una API que aqui no existe.
    (SALIDA / "static").mkdir()
    for recurso in ("style.css", "favicon.svg", "menu.js"):
        shutil.copy(RAIZ / "app" / "static" / recurso, SALIDA / "static" / recurso)

    # Sin esto, Pages ignora lo que empiece por guion bajo.
    (SALIDA / ".nojekyll").write_text("")

    print(f"\nListo en {SALIDA.relative_to(RAIZ)}/")
    print("Publicalo en Settings -> Pages -> rama main, carpeta /docs")


if __name__ == "__main__":
    exportar()
