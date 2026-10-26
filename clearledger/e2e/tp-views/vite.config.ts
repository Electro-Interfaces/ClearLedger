import { defineConfig, mergeConfig } from 'vite'
import base from '../../vite.config'
export default mergeConfig(base, defineConfig({
  cacheDir: 'node_modules/.vite-tp-views',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:15449') },
  optimizeDeps: { entries: ['e2e/tp-views/fixture.html'] },
  server: { host: '127.0.0.1', port: 15449, strictPort: true, proxy: { '/api': 'http://127.0.0.1:18549' } },
}))
