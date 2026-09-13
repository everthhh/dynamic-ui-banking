import { defineConfig, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

// `/chat` y `/action` son SSE (text/event-stream) de larga duración.
// sse_starlette manda `Connection: keep-alive` a propósito; el proxy de
// Node le agrega el suyo sin quitar el de arriba, y el navegador recibe
// `Connection: keep-alive, close` (duplicado). Ese header roto hace que el
// fetch del front termine el stream sin datos y sin error visible — nada se
// pinta y no hay pista en consola. Se quita el de arriba en `proxyRes` para
// que solo quede el que pone el proxy.
const SSE: ProxyOptions = {
  target: "http://localhost:8000",
  changeOrigin: true,
  configure: (proxy) => {
    proxy.on("proxyRes", (proxyRes) => {
      delete proxyRes.headers["connection"];
    });
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // El front habla siempre con rutas relativas; el proxy decide a dónde van.
    // Así el mismo build sirve en dev y detrás de un reverse proxy.
    proxy: {
      "/chat": SSE,
      "/action": SSE,
      "/session": SSE,
      "/api": "http://localhost:8000",
      "/a2ui": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
