import { defineConfig, mergeConfig } from 'vite'
import path from 'node:path'
import base from '../../vite.config'
export default mergeConfig(base, defineConfig({
  cacheDir: 'node_modules/.vite-counterparties',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:15446') },
  optimizeDeps: { entries: ['e2e/counterparties/fixture.html'] },
  plugins: [{ name: 'counterparty-test-company', enforce: 'pre', configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url?.split('?')[0] === '/contractors') req.url = '/e2e/counterparties/fixture.html'
      next()
    })
  }, transform(code, id) {
    if (id.includes('/node_modules/') || !/\.[jt]sx?(\?|$)/.test(id)) return
    return code.replaceAll(/from ['"](?:@\/contexts\/CompanyContext|\.\/CompanyContext)['"]/g,
      `from ${JSON.stringify(path.resolve(__dirname, 'company.ts'))}`)
  } }],
  server: { host: '127.0.0.1', port: 15446, strictPort: true, proxy: { '/api': 'http://127.0.0.1:18547' } },
}))
