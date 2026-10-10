import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Task-only API by default. Override explicitly for the legacy benchmark host.
const backendTarget = process.env.METRICSLEUTH_DEV_API_TARGET || 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/health': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
})
