@echo off
rem ---------------------------------------------------------------------------
rem  Seguimiento de rostro con MediaPipe + servo SG90 (Arduino)
rem
rem  Uso:
rem    Doble clic ............ camara + Arduino autodetectado
rem    iniciar.bat --dry-run .. sin Arduino (solo consola)
rem    iniciar.bat --simulate . con Arduino simulado
rem    iniciar.bat --port COM3  puerto explicito
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Seguimiento de rostro (MediaPipe + Arduino)

echo ==========================================================
echo   Seguimiento de rostro - MediaPipe + servo SG90
echo   Carpeta: %CD%
echo ==========================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro "python" en el PATH.
    echo         Instala Python 3.10 o superior y marca la casilla
    echo         "Add python.exe to PATH" durante la instalacion.
    echo.
    goto :fin_error
)

if not exist "models\face_landmarker.task" (
    echo [1/2] Falta el modelo, descargando... 3.7 MB
    python download_model.py
    if errorlevel 1 (
        echo.
        echo [ERROR] No se pudo descargar el modelo.
        echo         Revisa la conexion a internet y vuelve a intentarlo.
        goto :fin_error
    )
    echo.
)

echo [2/2] Iniciando...
echo.
python main.py %*
set "CODIGO=%ERRORLEVEL%"
echo.

if "%CODIGO%"=="0" goto :fin_ok
if "%CODIGO%"=="2" echo [ERROR] Falta el modelo. Ejecuta: python download_model.py
if "%CODIGO%"=="3" echo [ERROR] No se pudo abrir la camara. Cierra otras apps que la usen.
if "%CODIGO%"=="4" echo [ERROR] La camara no entrega imagen. Revisa el cable USB.
if "%CODIGO%"=="130" echo Programa interrumpido con Ctrl+C.

:fin_error
if not "%SEGUIMIENTO_SIN_PAUSA%"=="1" pause
endlocal
exit /b 1

:fin_ok
echo Programa cerrado correctamente.
if not "%SEGUIMIENTO_SIN_PAUSA%"=="1" pause
endlocal
exit /b 0
