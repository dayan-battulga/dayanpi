import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

const webDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  // Only DAYANPI_URL from web/.env.local, and only here in the dev server. You sign in on the dev
  // page itself: Chrome keeps the Pi's Secure session cookie on http://localhost too.
  const env = loadEnv(mode, webDir, "DAYANPI_");
  const toPi = { target: env.DAYANPI_URL, changeOrigin: true };
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": path.resolve(webDir, "src") } },
    // ES workers, so the camera test's worker can import ONNX Runtime, whose threads load that same file.
    worker: { format: "es" },
    build: {
      // Straight into the folder app.py already serves, so the Pi needs no Node and no new route.
      outDir: path.resolve(webDir, "../dayanpi/static"),
      emptyOutDir: true,
    },
    server: {
      // /video also covers /video/side.
      proxy: env.DAYANPI_URL ? { "/api": toPi, "/video": toPi } : undefined,
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
