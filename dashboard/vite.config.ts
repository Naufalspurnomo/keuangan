import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react-swc'

export default defineConfig({
  base: process.env.VITE_PUBLIC_BASE || '/',
  plugins: [react()],
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { environment: 'jsdom', globals: true, fileParallelism: false, maxWorkers: 1, testTimeout: 15_000 },
  server: {
    proxy: {
      '/api/dashboard': 'http://127.0.0.1:5000',
    },
  },
})
