#!/bin/bash
# Doble clic en el Finder y listo.
#
# La primera vez instala lo que falte -uv, el entorno, las dependencias- y las
# siguientes solo arranca. No pide contrasena ni toca nada fuera de esta
# carpeta. Cerrar la ventana detiene el servidor.
set -u
cd "$(dirname "$0")" || exit 1

VERDE=$'\033[32m'; GRIS=$'\033[90m'; ROJO=$'\033[31m'; FIN=$'\033[0m'
paso() { printf "%s▸ %s%s\n" "$VERDE" "$1" "$FIN"; }
aviso() { printf "%s  %s%s\n" "$GRIS" "$1" "$FIN"; }
error() { printf "%s✕ %s%s\n" "$ROJO" "$1" "$FIN"; }

printf "\n  ▌ %sCompás%s — playlists por momento\n\n" "$VERDE" "$FIN"

# --- 1. uv ------------------------------------------------------------------
UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -z "$UV" ]; then
  paso "Instalando uv (gestor de Python, no necesita permisos de administrador)"
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
    error "No se pudo instalar uv. Instálalo a mano: https://docs.astral.sh/uv/"
    read -r -p "Pulsa Intro para cerrar."; exit 1
  fi
  UV="$HOME/.local/bin/uv"
fi

# --- 2. entorno -------------------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  paso "Preparando el entorno (solo la primera vez, tarda un minuto)"
  "$UV" venv --python 3.13 .venv || { error "No se pudo crear el entorno."; read -r; exit 1; }
fi

# Se reinstala solo si requirements.txt es mas nuevo que la ultima instalacion.
if [ ! -f ".venv/.instalado" ] || [ requirements.txt -nt ".venv/.instalado" ]; then
  paso "Instalando dependencias"
  "$UV" pip install --python .venv/bin/python -r requirements.txt --quiet \
    || { error "Fallaron las dependencias."; read -r; exit 1; }
  touch ".venv/.instalado"
fi

# --- 3. configuracion -------------------------------------------------------
if [ ! -f ".env" ]; then
  cp .env.example .env
  aviso "Creado .env — las claves se piden en el navegador, no hace falta editarlo"
fi

# --- 4. arrancar ------------------------------------------------------------
paso "Arrancando en http://127.0.0.1:8000"
aviso "Deja esta ventana abierta. Ciérrala para detener Compás."
echo
(sleep 2 && open "http://127.0.0.1:8000" 2>/dev/null) &

# El codigo 3 lo emite la propia aplicacion cuando se guardan credenciales
# nuevas: reiniciar es la forma mas simple de recargarlas sin plumbing.
while true; do
  ./.venv/bin/python run.py
  codigo=$?
  [ "$codigo" -eq 3 ] || break
  paso "Recargando la configuración…"
done

echo
aviso "Compás se ha detenido."
read -r -p "Pulsa Intro para cerrar esta ventana."
