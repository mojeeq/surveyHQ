import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    host: true,
    // A dashboard can answer on its own hostname, and the dev server refuses
    // hosts it does not know. Production is nginx with `server_name _`, which
    // accepts any name; this is what lets the same thing be tried locally.
    allowedHosts: (process.env.DASHBOARD_DOMAIN
      ? [`.${process.env.DASHBOARD_DOMAIN}`]
      : []
    ).concat(['localhost', '127.0.0.1']),
    // The Host header has to survive the proxy, or the API cannot tell which
    // dashboard the browser asked for.
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
      '/health': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts', 'echarts-for-react'],
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
