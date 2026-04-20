import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

export default defineConfig({
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
