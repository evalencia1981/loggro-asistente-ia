# stop.ps1 — Detiene backend, frontend y túnel.
$ErrorActionPreference = "SilentlyContinue"

Write-Host "==> Deteniendo Loggro..." -ForegroundColor Cyan

# Puertos: los mismos que usa start.ps1 (ports.json). Solo se tocan los de ESTE
# proyecto, para no matar otros proyectos que esten corriendo (ver docs/PUERTOS.md).
$ports = Get-Content (Join-Path $PSScriptRoot "ports.json") -Raw | ConvertFrom-Json

foreach ($port in $ports.api, $ports.web) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
      Write-Host "   - cerrando PID $($_.OwningProcess) (puerto $port)"
      Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# Cerrar SOLO el tunel de este proyecto: el que apunta a nuestro puerto web.
# (Antes se mataban todos los cloudflared, lo que tumbaba el tunel de otros proyectos.)
Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match ":$($ports.web)\b" } |
  ForEach-Object {
    Write-Host "   - cerrando tunel (PID $($_.ProcessId))"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Write-Host "Listo. Todo detenido." -ForegroundColor Green
