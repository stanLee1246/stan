import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: { rollupOptions: { output: { manualChunks(id) {
    if (id.includes('/echarts/') || id.includes('/zrender/')) return 'charts'
    if (id.includes('/@vue/') || id.includes('/vue/') || id.includes('/vue-router/')) return 'vue'
  } } } },
  server: { port: 5173, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
  preview: { port: 4173, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
})
