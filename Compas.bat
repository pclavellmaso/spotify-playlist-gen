@echo off
REM Doble clic y listo. La primera vez instala lo que falte; las siguientes
REM solo arranca. No necesita permisos de administrador.
setlocal
cd /d "%~dp0"

echo.
echo   ^| Compas - playlists por momento
echo.

REM --- 1. uv -----------------------------------------------------------------
set "UV=uv"
where uv >nul 2>&1
if errorlevel 1 (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
  ) else (
    echo   ^> Instalando uv ^(gestor de Python^)
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
  )
)

REM --- 2. entorno ------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo   ^> Preparando el entorno ^(solo la primera vez^)
  "%UV%" venv --python 3.13 .venv || goto :fallo
)
if not exist ".venv\.instalado" (
  echo   ^> Instalando dependencias
  "%UV%" pip install --python .venv\Scripts\python.exe -r requirements.txt --quiet || goto :fallo
  echo ok> ".venv\.instalado"
)

REM --- 3. configuracion ------------------------------------------------------
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo   ^> Creado .env - las claves se piden en el navegador
)

REM --- 4. arrancar -----------------------------------------------------------
echo   ^> Arrancando en http://127.0.0.1:8000
echo   ^> Deja esta ventana abierta. Cierrala para detener Compas.
echo.
start "" /b cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"

:arrancar
".venv\Scripts\python.exe" run.py
REM El codigo 3 lo emite la aplicacion al guardar credenciales nuevas.
if errorlevel 3 if not errorlevel 4 (
  echo   ^> Recargando la configuracion...
  goto :arrancar
)
goto :fin

:fallo
echo.
echo   No se pudo preparar el entorno.
:fin
echo.
pause
