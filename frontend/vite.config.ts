import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The frontend never simulates anything.  Every number it shows came from the
// backend, which got it from the race engine -- so the dev server proxies /api
// straight through rather than the client knowing a host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
