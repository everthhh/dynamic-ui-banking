import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // El front habla siempre con rutas relativas; el proxy decide a dónde van.
    // Así el mismo build sirve en dev y detrás de un reverse proxy.
    proxy: {
      "/chat": "http://localhost:8000",
      "/action": "http://localhost:8000",
      "/api": "http://localhost:8000",
      "/a2ui": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
