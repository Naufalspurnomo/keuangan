import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react-swc'

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { environment: 'jsdom', globals: true },
  server: {
    proxy: {
      '/api/dashboard': 'http://127.0.0.1:5000',
    },
  },
})
