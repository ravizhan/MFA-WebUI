import { fileURLToPath, URL } from "node:url"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import tailwindcss from "@tailwindcss/vite"
import AutoImport from "unplugin-auto-import/vite"

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  plugins: [
    vue(),
    tailwindcss(),
    AutoImport({
      imports: ["vue"],
    }),
  ],
  build: {
    outDir: "../page",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:5566",
        changeOrigin: true,
      },
    },
  },
})
