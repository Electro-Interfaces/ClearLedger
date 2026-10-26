import { defineConfig, mergeConfig } from 'vite'
import base from '../../vite.config'
export default mergeConfig(base, defineConfig({
  cacheDir: 'node_modules/.vite-tech-connection',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:15439') },
  optimizeDeps: { entries: ['e2e/tech-connection/fixture.html'] },
  server: { host: '127.0.0.1', port: 15439, strictPort: true, proxy: { '/api': 'http://127.0.0.1:18539' } },
}))
