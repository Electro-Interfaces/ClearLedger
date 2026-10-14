// Публичная сборка: вход и страницы по ссылкам — то, что получает посетитель без входа
// (пункт 6 аудита безопасности 07.10.2026). Кладётся в dist/p и раздаётся под /p/;
// основное приложение (dist/assets) nginx стека отдаёт только с меткой входа.
// Собирается после основной: `npm run build` делает обе.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'fs'
import path from 'path'

const BUILD = new Date().toISOString().slice(0, 16).replace('T', ' ')

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(
      JSON.parse(fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8')).version),
    __APP_BUILD__: JSON.stringify(BUILD),
  },
  base: '/p/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: [
      // Демо-данные — карта API; в публичную сборку идёт пустая заглушка.
      { find: '@/demo/demoApi', replacement: path.resolve(__dirname, './src/public/demoStub.ts') },
      { find: '@', replacement: path.resolve(__dirname, './src') },
    ],
  },
  build: {
    outDir: 'dist/p',
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'public.html'),
      external: ['tesseract.js'],
    },
  },
  // Копию папки public/ основная сборка уже положила в dist — второй раз не нужна.
  publicDir: false,
})
