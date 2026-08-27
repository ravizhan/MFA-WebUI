import { fileURLToPath, URL } from "node:url"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import tailwindcss from "@tailwindcss/vite"
import AutoImport from "unplugin-auto-import/vite"
import Components from "unplugin-vue-components/vite"
import { NaiveUiResolver } from "unplugin-vue-components/resolvers"

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
    Components({
      resolvers: [NaiveUiResolver()],
    }),
  ],
  build: {
    outDir: "../page",
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules")) {
            if (id.includes("naive-ui")) return "naive-ui"
            if (/[\\/](vue|vue-router|pinia|vue-i18n|@vue)[\\/]/.test(id)) return "vendor-vue"
            if (id.includes("zod") || id.includes("cron-converter")) return "vendor-utils"
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
      },
    },
  },
})
