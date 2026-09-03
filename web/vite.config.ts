import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// API origin is configurable so no teammate's machine is baked into the repo.
// Override per-developer in web/.env.local (gitignored):
//   VITE_API_PROXY=http://kartik-pc:8016
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY || 'http://localhost:8016'

  return {
    plugins: [react()],
    // MapLibre parses GeoJSON in a web worker. Vite's dep pre-bundling rewrites
    // the worker entry so it never boots: raster tiles still draw (decoded on
    // the main thread) but every GeoJSON source hangs at loaded=false with no
    // error. Excluding it from optimizeDeps keeps the worker intact.
    optimizeDeps: { exclude: ['maplibre-gl'] },
    worker: { format: 'es' as const },
    server: {
      port: 3016,
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
  }
})
