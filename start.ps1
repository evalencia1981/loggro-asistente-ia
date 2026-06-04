# start.ps1 - Levanta TODO (backend + frontend + tunel) y muestra la URL publica.
# Uso:  click derecho > "Ejecutar con PowerShell"   o   en terminal:  .\start.ps1
# Para detener todo:  .\stop.ps1

$ErrorActionPreference = "SilentlyContinue"
$root     = $PSScriptRoot
$frontend = Join-Path $root "frontend"
$cf       = Join-Path $env:USERPROFILE "cloudflared.exe"

Write-Host "==> Loggro - arranque completo" -ForegroundColor Cyan

# 1) Liberar puertos por si quedaron procesos zombie de una corrida anterior
foreach ($port in 8000, 5173) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

# 2) Descargar cloudflared si no esta
if (-not (Test-Path $cf)) {
  Write-Host "==> Descargando cloudflared..." -ForegroundColor Yellow
  Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $cf -UseBasicParsing
}

# 3) Backend (FastAPI) en su propia ventana
Write-Host "==> Backend  -> http://localhost:8000" -ForegroundColor Green
Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList @(
  "-NoExit", "-Command", "python -X utf8 -m uvicorn backend.app:app --reload --port 8000"
)

# 4) Frontend (Vite) en su propia ventana
Write-Host "==> Frontend -> http://localhost:5173" -ForegroundColor Green
Start-Process -FilePath "powershell.exe" -WorkingDirectory $frontend -ArgumentList @(
  "-NoExit", "-Command", "npm run dev -- --strictPort"
)

# 5) Tunel de Cloudflare (oculto, con log para extraer la URL)
$out = Join-Path $env:TEMP "loggro-tunnel.out"
$err = Join-Path $env:TEMP "loggro-tunnel.err"
Remove-Item $out, $err -ErrorAction SilentlyContinue
Write-Host "==> Iniciando tunel..." -ForegroundColor Green
Start-Process -FilePath $cf -ArgumentList @("tunnel", "--url", "http://localhost:5173") -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden

# 6) Esperar y extraer la URL publica
$url = $null
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Seconds 1
  $txt = (Get-Content $out, $err -ErrorAction SilentlyContinue) -join "`n"
  $m = [regex]::Match($txt, "https://[a-z0-9-]+\.trycloudflare\.com")
  if ($m.Success) { $url = $m.Value; break }
}

Write-Host ""
if ($url) {
  $url | Out-File -FilePath (Join-Path $root "tunnel-url.txt") -Encoding ascii
  Write-Host "================================================================" -ForegroundColor Cyan
  Write-Host "  LISTO. URL publica (HTTPS, sirve para celular):" -ForegroundColor Cyan
  Write-Host "  $url" -ForegroundColor White
  Write-Host "================================================================" -ForegroundColor Cyan
  Write-Host "  (guardada tambien en tunnel-url.txt)"
  Write-Host "  Backend y Frontend abrieron en ventanas aparte."
  Write-Host "  Para detener todo:  .\stop.ps1"
} else {
  Write-Host "No se pudo leer la URL del tunel. Revisa: $err" -ForegroundColor Red
}
