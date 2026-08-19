# probar_catalogo.ps1 - Recorrido completo de la API de carta contra Loggro real.
#
# Hace el ciclo entero con un producto de prueba y LIMPIA al final (lo borra de
# Loggro y rompe el vinculo), asi se puede correr las veces que haga falta.
#
# Uso:   .\probar_catalogo.ps1
#        .\probar_catalogo.ps1 -Puerto 8090
#
# Requiere el backend levantado (start.bat) y CATALOGO_API_KEYS en el .env.

param(
  [int]$Puerto = 0,
  [string]$Clave = ""
)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot

# Puerto: de ports.json si no se pasa por parametro
if ($Puerto -eq 0) {
  $Puerto = (Get-Content (Join-Path $raiz "ports.json") -Raw | ConvertFrom-Json).api
}
$BASE = "http://127.0.0.1:$Puerto/api/catalogo"

# Clave: del .env si no se pasa por parametro
if (-not $Clave) {
  $linea = Select-String -Path (Join-Path $raiz ".env") -Pattern "^CATALOGO_API_KEYS=" |
           Select-Object -First 1
  if (-not $linea) { throw "No hay CATALOGO_API_KEYS en el .env" }
  # formato: app:clave[,app2:clave2]  ->  tomamos la clave de la primera app
  $Clave = (($linea.Line -replace "^CATALOGO_API_KEYS=", "") -split ",")[0].Split(":", 2)[1].Trim()
}

$cab = @{ "X-API-Key" = $Clave }

function Llamar {
  param([string]$Metodo, [string]$Ruta, $Cuerpo = $null)
  $args = @{ Method = $Metodo; Uri = "$BASE$Ruta"; Headers = $cab; UseBasicParsing = $true }
  if ($Cuerpo -ne $null) {
    $json = $Cuerpo | ConvertTo-Json -Depth 10 -Compress
    # UTF-8 explicito: si no, PowerShell 5.1 manda los acentos en ANSI y el
    # backend responde 400 al parsear el JSON.
    $args.Body = [System.Text.Encoding]::UTF8.GetBytes($json)
    $args.ContentType = "application/json; charset=utf-8"
  }
  # Se usa Invoke-WebRequest (no Invoke-RestMethod) para decodificar la respuesta
  # como UTF-8 a mano: PowerShell 5.1 asume ANSI cuando el Content-Type no trae
  # charset, y los nombres salian como "Costenita" -> "CosteÃ±ita".
  $resp = Invoke-WebRequest @args
  $texto = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
  return $texto | ConvertFrom-Json
}

function Titulo { param([string]$T) Write-Host "`n=== $T" -ForegroundColor Cyan }

$CODIGO = "DEMO-001"

Write-Host "API: $BASE" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1) conexion
Titulo "1. Conexion (GET /health)"
$h = Llamar GET "/health"
Write-Host "   app: $($h.app) | vinculos ya homologados: $($h.vinculos)"

# ---------------------------------------------- 2) homologar (no escribe nada)
Titulo "2. Homologar: comparar la carta contra Loggro (no escribe nada)"
$hom = Llamar POST "/homologar" @{ items = @(
    @{ codigo = "X-1"; nombre = "Aguila Light" },
    @{ codigo = "X-2"; nombre = "Costenita 175" },
    @{ codigo = $CODIGO; nombre = "ZZ DEMO Limonada de coco" }
) }
Write-Host "   vinculados=$($hom.vinculados)  sugeridos=$($hom.sugeridos)  nuevos=$($hom.nuevos)"
foreach ($i in $hom.items) {
  Write-Host "   - $($i.codigo) '$($i.nombre)' -> $($i.estado)"
  foreach ($c in $i.candidatos | Select-Object -First 2) {
    Write-Host "       $($c.parecido)  $($c.product_name)  `$$($c.precio_loggro)"
  }
}

# ------------------------------------------------------- 3) crear en Loggro
Titulo "3. Crear el producto en Loggro (POST /productos)"
Write-Host "   OJO: un codigo 'sugerido' que nadie confirmo se CREA como producto nuevo."
Write-Host "   Por eso el orden importa: homologar -> confirmar con POST /vinculos -> sincronizar." -ForegroundColor Yellow
$up = Llamar POST "/productos" @{ productos = @(
    @{ codigo = $CODIGO; nombre = "ZZ DEMO Limonada de coco"; precio = 15000
       categoria = "Cocteles"; descripcion = "producto de demostracion" }
) }
$r = $up.resultados[0]
Write-Host "   accion: $($r.accion) | product_id: $($r.product_id) | precio: $($r.producto.precio)"

# ------------------------------------------------------------ 4) idempotencia
Titulo "4. Mandar lo MISMO otra vez (debe decir sin_cambios)"
$up2 = Llamar POST "/productos" @{ productos = @(
    @{ codigo = $CODIGO; nombre = "ZZ DEMO Limonada de coco"; precio = 15000 }
) }
Write-Host "   accion: $($up2.resultados[0].accion)   <- no reescribe en Loggro"

# -------------------------------------------------------- 5) cambiar el precio
Titulo "5. Cambiar el precio (PATCH /productos/$CODIGO)"
$pa = Llamar PATCH "/productos/$CODIGO" @{ precio = 17500 }
Write-Host "   accion: $($pa.accion) | precio ahora: $($pa.producto.precio)"

# ---------------------------------------------------------- 6) cambiar nombre
Titulo "6. Cambiar el nombre"
$pn = Llamar PATCH "/productos/$CODIGO" @{ nombre = "ZZ DEMO Limonada de coco grande" }
Write-Host "   nombre ahora: $($pn.producto.nombre)"

# ------------------------------------------------------------- 7) desactivar
Titulo "7. Desactivar (DELETE /productos/$CODIGO, sin ?borrar)"
$de = Llamar DELETE "/productos/$CODIGO"
Write-Host "   accion: $($de.accion) | activo: $($de.producto.activo)"

# ------------------------------------------------ 8) flujo inverso Loggro->app
Titulo "8. Cambios desde Loggro (GET /cambios)"
$ca = Llamar GET "/cambios"
Write-Host "   cambios ajenos detectados: $($ca.total)   <- 0 esperado: todo lo hicimos nosotros"
$ce = Llamar GET "/cambios?incluir_eco=true"
Write-Host "   con incluir_eco=true: $($ce.total)"

# --------------------------------------------------------------- 9) limpieza
Titulo "9. Limpieza: borrar de Loggro el producto de demo"
$bo = Llamar DELETE "/productos/$($CODIGO)?borrar=true"
Write-Host "   accion: $($bo.accion)"

Write-Host "`nListo. El ciclo completo funciono y no quedo nada en Loggro." -ForegroundColor Green
Write-Host "Documentacion: docs\API_CATALOGO.md" -ForegroundColor DarkGray
