import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Every number on the season screens came from the backend, which got it from
// the race engine -- so the dev server proxies /api straight through rather
// than the client knowing a host.
//
// The one exception is the live race, which is a race being *driven* rather
// than a session being read back: sixty frames a second of physics and twenty
// driver models cannot come down a wire, so that page runs the simulation in
// the browser and takes only the circuit and the field from the API.
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
