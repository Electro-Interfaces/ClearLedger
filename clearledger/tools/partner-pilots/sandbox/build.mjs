// Актуальные public/main React исходники без генераторов release/PWA.
import { build } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
const root = fileURLToPath(new URL('../../../', import.meta.url))
const [origin, output] = process.argv.slice(2)
if (!/^https:\/\/127\.0\.0\.1:\d+$/.test(origin) || !output?.startsWith('/')) throw Error('loopback origin and absolute private output required')
await build({ root, configFile: `${root}/vite.public.config.ts`, envFile: false, logLevel: 'error',
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin) },
  build: { outDir: resolve(output, 'public'), emptyOutDir: true } })
await build({ root, configFile: false, envFile: false, logLevel: 'error', plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': `${root}/src` } },
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify(origin), '__APP_VERSION__': '"sandbox"', '__APP_BUILD__': '"synthetic"' },
  build: { outDir: resolve(output, 'main'), emptyOutDir: true,
    rollupOptions: { input: `${root}/index.html`, external: ['tesseract.js'] } } })
