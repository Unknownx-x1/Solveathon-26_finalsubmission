@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
)

echo [2/4] Activating virtual environment...
call ".venv\Scripts\activate.bat"

echo [3/4] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

if "%SECRET_KEY%"=="" (
    set SECRET_KEY=laundry-demo-secret-key
)

echo [4/4] Starting demo server on http://127.0.0.1:8000
echo.
echo Open another terminal and run:
echo cloudflared tunnel --url http://127.0.0.1:8000
echo.
waitress-serve --host 127.0.0.1 --port 8000 app:app

endlocal
