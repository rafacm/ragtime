import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

// Must match Django's STATIC_URL + DJANGO_VITE["default"]["static_url_prefix"].
// django-vite emits asset URLs as `{dev_server}/{STATIC_URL}{static_url_prefix}/...`
// in dev mode, so Vite has to serve from the same base or the browser 404s.
const VITE_BASE = "/static/frontend/";

export default defineConfig({
  base: VITE_BASE,
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    origin: "http://localhost:5173",
    cors: true,
  },
  build: {
    outDir: "dist",
    manifest: true,
    rollupOptions: {
      input: {
        chat: resolve(__dirname, "src/chat.tsx"),
      },
    },
  },
});
