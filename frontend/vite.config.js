import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // En la versión pública (`npm run build:static`) los archivos se enlazan en relativo (./assets/...):
  // así la web funciona en cualquier dirección, incluida una subcarpeta como
  // https://usuario.github.io/medipass-web/. En local (`npm run dev`) se queda en "/".
  base: mode === "static" ? "./" : "/",
}));
