@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD="
set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_UVICORN=.venv\Scripts\uvicorn.exe"
set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PORT=8000"

echo [1/4] Preparing Twins Bot LAN server...

where python > nul 2> nul
if not errorlevel 1 set "PYTHON_CMD=python"

if "%PYTHON_CMD%"=="" (
  where py > nul 2> nul
  if not errorlevel 1 set "PYTHON_CMD=py"
)

if "%PYTHON_CMD%"=="" (
  if exist "%CODEX_PY%" set "PYTHON_CMD=%CODEX_PY%"
)

if "%PYTHON_CMD%"=="" (
  echo.
  echo Python was not found. Please install Python and run this file again.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo [2/4] Creating the local app environment...
  "%PYTHON_CMD%" -m venv .venv
  if errorlevel 1 (
    echo.
    echo Could not create the app environment.
    pause
    exit /b 1
  )
)

echo [3/4] Installing required packages...
"%VENV_PY%" -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo.
  echo Package installation failed. Please check your internet connection and try again.
  pause
  exit /b 1
)

if not exist "backend\.env" (
  copy "backend\.env.example" "backend\.env" > nul
  echo.
  echo backend\.env was created.
  echo Add OPENAI_API_KEY to backend\.env, then run this file again.
  pause
  exit /b 1
)

for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /c:"IPv4"') do (
  set "LAN_IP=%%A"
  goto :found_ip
)

:found_ip
set "LAN_IP=%LAN_IP: =%"

echo.
echo [4/4] Starting LAN server...
echo.
echo Open this computer:
echo   http://127.0.0.1:%PORT%
echo.
echo Share this URL with people on the same Wi-Fi/network:
echo   http://%LAN_IP%:%PORT%
echo.
echo If other people cannot open it, allow Python/Uvicorn through Windows Firewall.
echo Keep this window open while others use the app.
echo.

start "" "http://127.0.0.1:%PORT%"
"%VENV_UVICORN%" backend.main:app --host 0.0.0.0 --port %PORT%

pause
