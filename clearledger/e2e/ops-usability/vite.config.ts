import { defineConfig, mergeConfig } from 'vite'
import base from '../../vite.config'
import path from 'node:path'

// Настоящие компоненты, заменены только контексты компании/отборов. Запросы
// настоящего apiClient перехватывает Playwright. В production этого плагина нет.
export default mergeConfig(base, defineConfig({
  cacheDir: process.env.OPS_QA_CACHE ?? 'node_modules/.vite-ops-qa',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:3199') },
  optimizeDeps: { entries: ['e2e/ops-usability/fixture.html'] },
  plugins: [{
    name: 'ops-component-fixture',
    enforce: 'pre',
    transform(code, id) {
      const target = id.split('?')[0]
      if (!/\/(WorkspaceFilterBar|NetworkStatePanel|NetworkReliabilityPanel|NetworkVendorsPanel|OpsTicketsPanel|useMonitorScope|BulkTicketDialog)\.tsx?$/.test(target)) return
      const hooks = JSON.stringify(path.resolve(__dirname, 'hooks.tsx'))
      let source = code.replace(/from ['"]@\/contexts\/(CompanyContext|FilterContext)['"]/g, `from ${hooks}`)
      if (target.endsWith('/WorkspaceFilterBar.tsx')) source += '\nexport { PeriodControl }\n'
      return source
    },
  }],
  server: { host: '127.0.0.1', port: 3199, strictPort: true },
}))
