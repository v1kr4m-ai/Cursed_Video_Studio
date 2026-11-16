@echo off
rem Double-click to start CineFlow AI: backend + desktop window.
rem Closing the window (or this console) stops the backend and frees port 8765.
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
set PORT=8765

rem Free the port if a previous run did not shut down cleanly.
call :freeport

echo Starting CineFlow backend on port %PORT%...
start "CineFlow backend" /min cmd /c "cd /d "%~dp0backend" && uv run uvicorn cineflow.api:app --host 127.0.0.1 --port %PORT%"

rem Wait up to 30 s for the backend to answer.
set /a tries=0
:wait
curl -s -o nul http://127.0.0.1:%PORT%/health && goto ready
set /a tries+=1
if %tries% geq 60 (
  echo Backend did not start. See the "CineFlow backend" window for the error.
  pause
  goto stop
)
timeout /t 1 /nobreak >nul
goto wait

:ready
echo Backend ready. Opening the app...
cd /d "%~dp0ui"
if not exist node_modules call npm install
call npm run tauri dev

:stop
echo Stopping backend...
call :freeport
taskkill /fi "WINDOWTITLE eq CineFlow backend*" /t /f >nul 2>&1
echo Done. Port %PORT% is free.
endlocal
exit /b

:freeport
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:%PORT% .*LISTENING"') do taskkill /pid %%p /t /f >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:1420 .*LISTENING"') do taskkill /pid %%p /t /f >nul 2>&1
exit /b
