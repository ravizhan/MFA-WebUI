import UnoCSS from 'unocss/vite'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

import AutoImport from 'unplugin-auto-import/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'
import Components from 'unplugin-vue-components/vite'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig({
  plugins: [
    vue(),
    UnoCSS(),
    AutoImport({
      imports: ["vue"],
    }),
    Components({
      resolvers: [NaiveUiResolver()],
    }),
    visualizer({
      gzipSize: true,
      brotliSize: true,
      emitFile: false,
      filename: "test.html",
    }),
  ],
  build: {
    outDir: "../page",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:55666",
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
