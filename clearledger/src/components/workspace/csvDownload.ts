/**
 * Выгрузка таблицы экрана в CSV — тот же формат, что отдаёт станция.
 *
 * Точка с запятой и UTF-8 BOM: Excel открывает такой файл двойным кликом и не
 * ломает кириллицу, поэтому офис и АЗС смотрят на одно и то же. Данные уже в
 * браузере — ходить за ними на сервер второй раз незачем.
 */
export function csvDownload(имя: string, заголовки: string[], строки: (string | number | null | undefined)[][]) {
  const ячейка = (v: string | number | null | undefined) =>
    `"${String(v ?? '').replace(/"/g, '""')}"`
  const текст = '﻿' + [заголовки, ...строки]
    .map((r) => r.map(ячейка).join(';'))
    .join('\r\n')
  const url = URL.createObjectURL(new Blob([текст], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = имя.endsWith('.csv') ? имя : `${имя}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
