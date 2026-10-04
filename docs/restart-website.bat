@echo off
setlocal
rem Restarts the Litter-ally Trash website: stops every running web_server.py, then starts one.
rem Works from any clone: the repository root is the folder above this script.
rem Usage: restart-website.bat [web_server.py options]
rem   No options = --host 0.0.0.0 --no-lid  (HTTPS on the local Wi-Fi, so phones can connect and use their cameras)
rem   This laptop only: restart-website.bat --host 127.0.0.1 --http --no-lid
rem   Example:   restart-website.bat --host 0.0.0.0 --enable-lid --lid-host 192.168.1.50

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
if not exist "web_server.py" (
  echo Could not find web_server.py in "%ROOT%". Keep this script in the docs folder of the repository.
  exit /b 1
)

set "PYTHON=%ROOT%\BRH_Test\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo No virtual environment at BRH_Test\.venv; using python from PATH.
  set "PYTHON=python"
)

echo Stopping any running website...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object CommandLine -like '*web_server.py*' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; for ($i = 0; $i -lt 20 -and (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 500 }"

set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--host 0.0.0.0 --no-lid"

echo Starting: web_server.py %ARGS%
echo Open the address it prints (https://^<this laptops Wi-Fi IP^>:8000 on the Wi-Fi) once it says "Model ready." Press Ctrl+C to stop.
"%PYTHON%" -u web_server.py %ARGS%
