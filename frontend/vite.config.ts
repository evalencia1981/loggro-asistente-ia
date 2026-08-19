import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Los puertos viven en ports.json (raíz del repo) para que start.ps1, stop.ps1 y
// Vite usen siempre los mismos. Cada proyecto tiene su rango: ver docs/PUERTOS.md.
const ports = JSON.parse(
  readFileSync(fileURLToPath(new URL("../ports.json", import.meta.url)), "utf-8"),
) as { api: number; web: number };

// El frontend llama a /api/* y Vite lo redirige al backend FastAPI.
// Así evitamos CORS y queda igual que en producción (un solo origen).
export default defineConfig({
  plugins: [react()],
  server: {
    port: ports.web,
    strictPort: true, // si el puerto está ocupado, fallar en vez de saltar a otro
    host: true, // escucha en todas las interfaces (para túnel/red local)
    allowedHosts: [".trycloudflare.com"], // acepta cualquier subdominio del túnel
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${ports.api}`,
        changeOrigin: true,
      },
    },
  },
});
