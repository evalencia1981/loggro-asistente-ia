# Registro de puertos por proyecto

Para poder tener varios proyectos levantados al mismo tiempo sin que se pisen.
**Cada proyecto tiene un bloque de 10 puertos**; dentro del bloque, por convención:

| Offset | Uso |
|---|---|
| `+0` | API / backend |
| `+1` | Web / frontend |
| `+2..+9` | Libre para lo que necesite ese proyecto (worker, base de datos local, docs…) |

## Asignación

| Bloque | Proyecto | API | Web | Estado |
|---|---|---|---|---|
| 8080–8089 | **Apptender** | 8080 | 8081 | en uso |
| 8090–8099 | **Loggro** (este repo) | 8090 | 8091 | en uso |
| 8100–8109 | **Reparte** | 8100 | 8101 | reservado |
| 8110–8119 | _(libre)_ | | | |

> Antes este proyecto usaba 8000 (API) y 5173 (Vite por defecto). Se movió a su
> bloque para no chocar con otros proyectos ni con el 5173 que cualquier Vite toma
> por defecto.

## Cómo se aplica en cada repo

La fuente de verdad es **`ports.json`** en la raíz del proyecto:

```json
{ "proyecto": "loggro", "api": 8090, "web": 8091 }
```

Lo leen los tres sitios que necesitan saber el puerto, así que se cambia en un solo lugar:

| Quién | Cómo lo lee |
|---|---|
| `start.ps1` | `Get-Content ports.json \| ConvertFrom-Json` → arranca uvicorn y el túnel |
| `stop.ps1` | igual → mata **solo** los procesos de estos puertos |
| `frontend/vite.config.ts` | `readFileSync("../ports.json")` → `server.port` y el proxy `/api` |

Para cambiar de puertos: editar `ports.json` y volver a levantar. Nada más.

## Reglas para no pisarse

1. **`strictPort` activado** en Vite: si el puerto está ocupado, falla en vez de saltar
   a otro en silencio (que es como uno termina sin saber en qué puerto quedó cada cosa).
2. **`stop.ps1` solo mata lo suyo**: filtra por los puertos del `ports.json` propio y,
   para el túnel de Cloudflare, por el que apunta a su puerto web.
3. **Al crear un proyecto nuevo**: tomar el siguiente bloque libre de esta tabla,
   crear su `ports.json` y anotarlo aquí.
