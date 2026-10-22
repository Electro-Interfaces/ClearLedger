import { defineConfig, mergeConfig } from 'vite'
import path from 'node:path'
import base from '../../vite.config'
export default mergeConfig(base, defineConfig({
  cacheDir: 'node_modules/.vite-location-contacts',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:15437') },
  optimizeDeps: { entries: ['e2e/location-contacts/fixture.html'] },
  plugins: [{ name: 'location-contact-fixture', enforce: 'pre', transform(code, id) {
    if (!id.split('?')[0].endsWith('/LocationContactsBlock.tsx')) return
    return code.replace("from '@/contexts/CompanyContext'", `from ${JSON.stringify(path.resolve(__dirname, 'company.ts'))}`)
  } }],
  server: { host: '127.0.0.1', port: 15437, strictPort: true, proxy: { '/api': 'http://127.0.0.1:18538' } },
}))
