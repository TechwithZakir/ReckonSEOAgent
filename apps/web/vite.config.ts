import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  envDir: '../..',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/docs': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/openapi.json': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'node',
    pool: 'vmThreads',
  },
})
