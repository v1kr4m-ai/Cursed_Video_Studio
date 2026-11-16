# Starts the CineFlow backend, waits for /health, runs the Tauri window, stops the backend on exit.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"

$backend = Start-Process -FilePath "uv" -WorkingDirectory "$root\backend" -PassThru -WindowStyle Minimized `
    -ArgumentList "run", "uvicorn", "cineflow.api:app", "--host", "127.0.0.1", "--port", "8765"
try {
    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
        if ($backend.HasExited) { throw "Backend exited early (code $($backend.ExitCode)). Is port 8765 already in use?" }
        try { $ready = (Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 2).status -in "ok", "degraded" }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "Backend did not answer /health within 30 s." }
    Push-Location "$root\ui"
    try {
        if (-not (Test-Path node_modules)) { npm install }
        npm run tauri dev
    } finally { Pop-Location }
} finally {
    # uv spawns python as a child: kill the whole tree.
    if ($backend -and -not $backend.HasExited) { taskkill /PID $backend.Id /T /F | Out-Null }
}
