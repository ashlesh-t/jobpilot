import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// The build output is committed and force-included into the Python wheel, so a
// `pipx install jobpilot-ai` needs no Node toolchain. Assets are emitted with relative
// paths and no external requests, which is what lets the UI work fully offline.
export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Charts are heavy and only the dashboard needs them — keep them out of the
        // shell chunk so first paint stays fast.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // `npm run dev` talks to a locally running `jobpilot serve`.
      '/api': 'http://127.0.0.1:8787',
      '/runs': 'http://127.0.0.1:8787',
      '/phases': 'http://127.0.0.1:8787',
      '/config': 'http://127.0.0.1:8787',
      '/engines': 'http://127.0.0.1:8787',
      '/doctor': 'http://127.0.0.1:8787',
      '/schedule': 'http://127.0.0.1:8787',
      '/health': 'http://127.0.0.1:8787',
    },
  },
})
