import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  base: '/ClearLedger/',
  plugins: [
    react(),
    tailwindcss(),
    // Dev: редирект /ClearLedger (без завершающего слэша) → /ClearLedger/ (base-path),
    // чтобы URL без слэша не упирался в подсказку Vite, а сразу открывал приложение.
    {
      name: 'redirect-base-no-slash',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/ClearLedger') {
            res.statusCode = 301
            res.setHeader('Location', '/ClearLedger/')
            res.end()
            return
          }
          next()
        })
      },
    },
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-radix': [
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-tabs',
            '@radix-ui/react-tooltip',
            '@radix-ui/react-select',
            '@radix-ui/react-alert-dialog',
            '@radix-ui/react-popover',
          ],
          'vendor-xlsx': ['xlsx'],
        },
      },
    },
  },
  server: {
    port: 3010,
    open: true,
    proxy: {
      '/tms': {
        target: 'https://pos.autooplata.ru',
        changeOrigin: true,
        secure: true,
      },
      '/msto': {
        target: 'http://46.229.214.21:3000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/msto/, ''),
      },
      '/tradecorp': {
        target: 'https://api.autooplata.ru',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/tradecorp/, ''),
      },
    },
  },
})
