import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss()],
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
    },
  },
})
