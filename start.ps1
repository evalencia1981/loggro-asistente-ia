# start.ps1 - Levanta TODO (backend + frontend + tunel) y muestra la URL publica.
# Uso:  click derecho > "Ejecutar con PowerShell"   o   en terminal:  .\start.ps1
# Para detener todo:  .\stop.ps1

$ErrorActionPreference = "SilentlyContinue"
$root     = $PSScriptRoot
$frontend = Join-Path $root "frontend"
$cf       = Join-Path $env:USERPROFILE "cloudflared.exe"

# Puertos: fuente unica en ports.json (la misma que lee vite.config.ts).
# Cada proyecto tiene su propio rango; ver docs/PUERTOS.md.
$ports    = Get-Content (Join-Path $root "ports.json") -Raw | ConvertFrom-Json
$portApi  = $ports.api
$portWeb  = $ports.web

Write-Host "==> Loggro - arranque completo (api $portApi / web $portWeb)" -ForegroundColor Cyan

# 1) Liberar puertos por si quedaron procesos zombie de una corrida anterior
foreach ($port in $portApi, $portWeb) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

# 2) Descargar cloudflared si no esta
if (-not (Test-Path $cf)) {
  Write-Host "==> Descargando cloudflared..." -ForegroundColor Yellow
  Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $cf -UseBasicParsing
}

# 3) Backend (FastAPI) en su propia ventana
Write-Host "==> Backend  -> http://localhost:$portApi" -ForegroundColor Green
Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList @(
  "-NoExit", "-Command", "python -X utf8 -m uvicorn backend.app:app --reload --port $portApi"
)

# 4) Frontend (Vite) en su propia ventana. El puerto sale de ports.json (vite.config.ts).
# Vite 5 necesita Node >= 18. Si el node activo de nvm es mas viejo, buscamos uno
# valido y lo anteponemos al PATH SOLO en esta ventana: no se cambia la version
# global, que pueden estar usando los otros proyectos.
$nodeDir = ""
$verNode = (& node -v) 2>$null
$mayor   = if ($verNode -match '^v(\d+)') { [int]$Matches[1] } else { 0 }
if ($mayor -lt 18) {
  $nvmRoot = if ($env:NVM_HOME) { $env:NVM_HOME } else { Join-Path $env:LOCALAPPDATA "nvm" }
  $cand = Get-ChildItem $nvmRoot -Directory -Filter "v*" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^v(\d+)' -and [int]$Matches[1] -ge 18 } |
    Sort-Object { [int]($_.Name -replace '^v(\d+).*', '$1') } -Descending |
    Select-Object -First 1
  if ($cand) {
    $nodeDir = $cand.FullName
    Write-Host "==> Node activo $verNode es viejo para Vite; uso $($cand.Name)" -ForegroundColor Yellow
  } else {
    Write-Host "==> AVISO: Node $verNode es menor que 18 y no hay otro en nvm. Vite fallara." -ForegroundColor Red
  }
}
$cmdWeb = if ($nodeDir) { "`$env:PATH = '$nodeDir;' + `$env:PATH; npm run dev" } else { "npm run dev" }

Write-Host "==> Frontend -> http://localhost:$portWeb" -ForegroundColor Green
Start-Process -FilePath "powershell.exe" -WorkingDirectory $frontend -ArgumentList @(
  "-NoExit", "-Command", $cmdWeb
)

# 5) Tunel de Cloudflare (oculto, con log para extraer la URL)
$out = Join-Path $env:TEMP "loggro-tunnel.out"
$err = Join-Path $env:TEMP "loggro-tunnel.err"
Remove-Item $out, $err -ErrorAction SilentlyContinue
Write-Host "==> Iniciando tunel..." -ForegroundColor Green
Start-Process -FilePath $cf -ArgumentList @("tunnel", "--url", "http://localhost:$portWeb") -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden

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
