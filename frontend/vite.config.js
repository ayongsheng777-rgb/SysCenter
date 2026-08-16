import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发态：/api 代理到本机后端（8352）
// 生产态：由 nginx（Docker）反代 /api 到 host.docker.internal:8352
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8352'
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500
  }
})
