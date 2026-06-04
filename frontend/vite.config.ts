import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// El frontend llama a /api/* y Vite lo redirige al backend FastAPI (puerto 8000).
// Así evitamos CORS y queda igual que en producción (un solo origen).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // escucha en todas las interfaces (para túnel/red local)
    allowedHosts: [".trycloudflare.com"], // acepta cualquier subdominio del túnel
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
