import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: process.env.BRIDGE_URL || 'http://127.0.0.1:58081',
        changeOrigin: true,
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/three/')) return 'globe'
          if (id.includes('/echarts/') || id.includes('/zrender/'))
            return 'charts'
        },
      },
    },
  },
})
