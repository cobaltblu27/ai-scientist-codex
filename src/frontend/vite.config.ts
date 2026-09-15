import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` proxies /api to the Python server (`ai-scientist dashboard`); `ai-scientist dashboard --dev`
// runs this for you and sets VITE_API_PROXY to wherever it bound the API.
// Build: output lands in ../dashboard/dist (package data of the `dashboard` Python package), which the
// Python server serves directly and the release wheel ships.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../dashboard/dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8765" },
  },
});
