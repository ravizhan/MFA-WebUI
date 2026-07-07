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
    cssMinify: "lightningcss",
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (
            id.includes("/node_modules/vue/") ||
            id.includes("/node_modules/vue-router/") ||
            id.includes("/node_modules/pinia/") ||
            id.includes("/node_modules/vue-i18n/")
          ) {
            return "vendor-vue"
          }
          if (id.includes("/node_modules/marked/") || id.includes("/node_modules/dompurify/")) {
            return "vendor-markdown"
          }
          if (id.includes("/node_modules/vue-draggable-plus/")) {
            return "vendor-drag"
          }
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:5566",
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
