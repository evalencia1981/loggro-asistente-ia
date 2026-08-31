# stop.ps1 — Detiene backend, frontend y túnel.
$ErrorActionPreference = "SilentlyContinue"

Write-Host "==> Deteniendo Loggro..." -ForegroundColor Cyan

# Puertos: los mismos que usa start.ps1 (ports.json). Solo se tocan los de ESTE
# proyecto, para no matar otros proyectos que esten corriendo (ver docs/PUERTOS.md).
$ports = Get-Content (Join-Path $PSScriptRoot "ports.json") -Raw | ConvertFrom-Json

function Test-PuertoOcupado([int]$puerto) {
  # Un intento de conexion real. Get-NetTCPConnection no basta: un worker
  # huerfano puede seguir atendiendo por un socket heredado sin figurar como
  # dueno del listener.
  $c = New-Object Net.Sockets.TcpClient
  try { $c.Connect("127.0.0.1", $puerto); return $c.Connected }
  catch { return $false }
  finally { $c.Close() }
}

# 1 y 2) Matar el ARBOL de cada proceso que escuche en nuestros puertos, y barrer
#    los workers huerfanos que queden. Con Stop-Process se mataba solo al padre;
#    uvicorn --reload corre la app en un proceso hijo (multiprocessing.spawn) que
#    hereda el socket y sobrevivia, siguiendo atendiendo con el CODIGO VIEJO. Se
#    llegaron a ver tres procesos escuchando el mismo puerto a la vez, y los
#    reinicios no surtian efecto.
#
#    Va en un bucle porque matar un padre destapa al siguiente: Get-NetTCPConnection
#    no lista de una todos los duenos de un socket compartido. Tres vueltas bastan;
#    el limite evita quedarse girando si algo no cede.
for ($vuelta = 1; $vuelta -le 3; $vuelta++) {
  $pendientes = @($ports.api, $ports.web) | Where-Object { Test-PuertoOcupado $_ }
  if (-not $pendientes) { break }

  foreach ($port in $pendientes) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique |
      ForEach-Object {
        Write-Host "   - cerrando PID $_ y sus hijos (puerto $port)"
        taskkill /F /T /PID $_ 2>&1 | Out-Null
      }
  }

  # Workers huerfanos: hijos de uvicorn cuyo padre ya no existe. Solo se barren si
  # algun puerto SIGUE contestando, para no tocar procesos sanos de otros proyectos.
  if (@($ports.api, $ports.web) | Where-Object { Test-PuertoOcupado $_ }) {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -match 'multiprocessing\.spawn' } |
      ForEach-Object {
        $proc = $_
        if ($proc.CommandLine -match 'parent_pid=(\d+)') {
          $padre = [int]$Matches[1]
          if (-not (Get-Process -Id $padre -ErrorAction SilentlyContinue)) {
            Write-Host "   - cerrando worker huerfano PID $($proc.ProcessId) (padre $padre ya no existe)"
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
          }
        }
      }
  }
}

# 3) Cerrar SOLO el tunel de este proyecto: el que apunta a nuestro puerto web.
# (Antes se mataban todos los cloudflared, lo que tumbaba el tunel de otros proyectos.)
Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match ":$($ports.web)\b" } |
  ForEach-Object {
    Write-Host "   - cerrando tunel (PID $($_.ProcessId))"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

# 4) Verificar de verdad que quedaron libres: si algo sigue atendiendo, decirlo
#    en vez de anunciar un "todo detenido" que no es cierto.
$ocupados = @($ports.api, $ports.web) | Where-Object { Test-PuertoOcupado $_ }
if ($ocupados) {
  Write-Host "AVISO: estos puertos siguen ocupados: $($ocupados -join ', ')" -ForegroundColor Red
  Write-Host "       Revisa con:  netstat -ano -p TCP | findstr :$($ocupados[0])"
} else {
  Write-Host "Listo. Todo detenido." -ForegroundColor Green
}
