import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3016,
    proxy: {
      '/api': { target: 'http://localhost:8016', changeOrigin: true },
    },
  },
})
