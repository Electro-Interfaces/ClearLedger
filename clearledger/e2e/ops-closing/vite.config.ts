import { defineConfig, mergeConfig } from 'vite'
import path from 'node:path'
import base from '../../vite.config'

export default mergeConfig(base, defineConfig({
  cacheDir: 'node_modules/.vite-ops-closing-test',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:3206') },
  optimizeDeps: { entries: ['e2e/ops-closing/fixture.html'] },
  plugins: [{
    name: 'closing-test-company-context', enforce: 'pre',
    transform(_code, id) {
      if (id.split('?')[0].endsWith('/contexts/CompanyContext.tsx')) {
        return `export { useCompany } from ${JSON.stringify(path.resolve(__dirname, 'company.tsx'))}`
      }
    },
  }],
  server: { host: '127.0.0.1', port: 3206, strictPort: true, open: false },
}))
