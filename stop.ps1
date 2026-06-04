# stop.ps1 — Detiene backend, frontend y túnel.
$ErrorActionPreference = "SilentlyContinue"

Write-Host "==> Deteniendo Loggro..." -ForegroundColor Cyan

# Cerrar puertos del backend (8000) y frontend (5173)
foreach ($port in 8000, 5173) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
      Write-Host "   - cerrando PID $($_.OwningProcess) (puerto $port)"
      Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# Cerrar el túnel
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "   - cerrando tunel (PID $($_.Id))"
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

Write-Host "Listo. Todo detenido." -ForegroundColor Green
