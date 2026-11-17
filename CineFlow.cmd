@echo off
rem Double-click to start CineFlow AI: backend + desktop window.
rem Closing the window stops CineFlow's own backend and frees its port.
rem It never stops other programs: if the port is taken by something else, it says so and exits.
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
set PORT=47615

rem Stop CineFlow processes left over from an earlier run (matched by command line, not by port).
call :stopours

rem Refuse to start if another program holds the port.
netstat -ano | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" >nul && (
  echo Port %PORT% is used by another program, not CineFlow. Close it or change PORT in this file.
  pause
  exit /b 1
)

echo Starting CineFlow backend on port %PORT%...
start "CineFlow backend" /min cmd /c "cd /d "%~dp0backend" && uv run uvicorn cineflow.api:app --host 127.0.0.1 --port %PORT%"

rem Wait up to 60 s for /health to answer as CineFlow.
set /a tries=0
:wait
curl -s http://127.0.0.1:%PORT%/health 2>nul | findstr /c:"\"service\":\"cineflow\"" >nul && goto ready
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
set VITE_API_URL=http://127.0.0.1:%PORT%
if not exist node_modules call npm install
call npm run tauri dev

:stop
echo Stopping CineFlow...
call :stopours
echo Done. Port %PORT% is free.
endlocal
exit /b

:stopours
rem Only processes whose command line is CineFlow's backend, or this project's Vite/Tauri dev server.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'cineflow\.api:app' -or ($_.CommandLine -match 'Cursed_Video_Studio' -and $_.CommandLine -match 'vite|cineflow-desktop')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
exit /b
