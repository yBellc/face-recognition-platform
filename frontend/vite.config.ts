import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3001,
    host: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:9091",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:9091",
        changeOrigin: true,
      },
    },
  },
});
