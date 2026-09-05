import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'fs'
import path from 'path'

// Метка сборки: по ней приложение понимает, что на сервере лежит уже другая версия.
// Дата, а не номер тега: тег знает только выкатывающий скрипт, а метка нужна коду.
const BUILD = new Date().toISOString().slice(0, 16).replace('T', ' ')
const BASE_PATH = process.env.VITE_BASE_PATH || '/'
const PWA_BRAND = process.env.VITE_ECOSYSTEM_BRAND?.trim() || 'Рабочее пространство'
const PWA_APPEARANCES: Record<string, {
  assetDir: string
  themeColor: string
  backgroundColor: string
}> = {
  'Аудит': { assetDir: 'office', themeColor: '#293991', backgroundColor: '#f3f5ff' },
  'РусГидро': { assetDir: 'rushydro', themeColor: '#006a9f', backgroundColor: '#eefaff' },
  'ГИГ': { assetDir: 'gig', themeColor: '#a84312', backgroundColor: '#fff7ed' },
}
const PWA_APPEARANCE = PWA_APPEARANCES[PWA_BRAND]

function baseUrl(pathname = '') {
  const base = `/${BASE_PATH.replace(/^\/+|\/+$/g, '')}`.replace('//', '/')
  return `${base === '/' ? '/' : `${base}/`}${pathname.replace(/^\//, '')}`
}

/**
 * `version.json` рядом со сборкой — единственный способ для открытой вкладки узнать
 * о новой выкатке. Приложение спрашивает его при возврате в окно и раз в 10 минут:
 * на телефоне вкладка живёт неделями, и человек смотрит на цифры вчерашней сборки,
 * не подозревая об этом.
 */
function versionFile() {
  return {
    name: 'space-version-file',
    apply: 'build' as const,
    closeBundle() {
      const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'))
      fs.writeFileSync(path.resolve(__dirname, 'dist/version.json'),
        JSON.stringify({ version: pkg.version, build: BUILD }, null, 2))
    },
  }
}

function pwaFiles() {
  const manifest = {
    name: `${PWA_BRAND} — рабочее пространство`,
    short_name: PWA_BRAND,
    description: 'Рабочее пространство компании: приложения, данные, задачи и коммуникации',
    id: baseUrl(),
    start_url: baseUrl('pwa-start'),
    scope: baseUrl(),
    display: 'standalone',
    display_override: ['standalone'],
    background_color: PWA_APPEARANCE?.backgroundColor ?? '#f4f6fb',
    theme_color: PWA_APPEARANCE?.themeColor ?? '#1d4ed8',
    lang: 'ru',
    categories: ['business', 'productivity'],
    prefer_related_applications: false,
    icons: [
      { src: baseUrl('icon-192.png'), sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: baseUrl('icon-512.png'), sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: baseUrl('icon-maskable-512.png'), sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
    shortcuts: [
      { name: 'Рабочий стол', url: baseUrl() },
      { name: 'Пульс', url: baseUrl('pwa-start') },
      { name: 'Моя работа', url: baseUrl('docs/work?view=today') },
    ],
  }

  return {
    name: 'space-pwa-files',
    transformIndexHtml(html: string) {
      const shortName = PWA_BRAND
        .replaceAll('&', '&amp;')
        .replaceAll('"', '&quot;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
      return html
        .replaceAll('__PWA_SHORT_NAME__', shortName)
        .replaceAll('__PWA_THEME_COLOR__', PWA_APPEARANCE?.themeColor ?? '#1d4ed8')
    },
    writeBundle() {
      const contents = `${JSON.stringify(manifest, null, 2)}\n`
      fs.writeFileSync(path.resolve(__dirname, 'dist/manifest.webmanifest'), contents)
      // Старый адрес оставляем совместимым для уже установленных первых PWA.
      fs.writeFileSync(path.resolve(__dirname, 'dist/pulse.webmanifest'), contents)

      // Имена файлов снаружи одинаковы, но содержимое своё для каждого пространства:
      // старые установки, push-уведомления и iOS продолжают обращаться к корню домена.
      if (PWA_APPEARANCE) {
        const sourceDir = path.resolve(__dirname, 'public/pwa', PWA_APPEARANCE.assetDir)
        for (const name of ['icon-192.png', 'icon-512.png', 'icon-maskable-512.png',
          'apple-touch-icon.png']) {
          fs.copyFileSync(path.join(sourceDir, name), path.resolve(__dirname, 'dist', name))
        }
        fs.copyFileSync(path.join(sourceDir, 'icon.svg'), path.resolve(__dirname, 'dist/favicon.svg'))
      }
    },
  }
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(
      JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8')).version),
    __APP_BUILD__: JSON.stringify(BUILD),
  },
  // Пространство живёт в КОРНЕ своего домена: `office.dataworker.ru/pulse`, а не
  // `.../ClearLedger/pulse`. «ClearLedger» — внутреннее имя репозитория; наружу
  // оно не выходит (white-label), а в адресной строке заказчика читалось как
  // чужой продукт. Переопределяется сборкой, если стек ставит SPA под путь.
  base: BASE_PATH,
  plugins: [
    react(),
    tailwindcss(),
    versionFile(),
    pwaFiles(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      // OCR (tesseract.js) — опциональный динамический импорт в try/catch; пакет не
      // установлен (OCR деградирует мягко). Externalize, чтобы сборка не падала.
      external: ['tesseract.js'],
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
