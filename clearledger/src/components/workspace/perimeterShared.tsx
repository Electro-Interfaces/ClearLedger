/**
 * Общее для экранов «Периметра»: выгрузка со следом в журнале и подача подтверждения.
 *
 * Выгрузка из этого продукта — не то же самое, что из «Реализации». Здесь в таблицах
 * имена людей, суммы наличных расчётов и телефоны, и настройки прямо обещают: «каждая
 * выгрузка попадает в журнал действий пространства». Обещание держалось на том, что
 * автор экрана не забудет позвать `logExport` рядом с `exportTable` — из восьми кнопок
 * его звали две. Поэтому здесь один компонент, который делает оба действия сразу:
 * забыть след теперь не на чем.
 */
import { exportTable } from '@/services/booksExport'
import { logExport } from '@/services/perimeterService'
import { ExportButton } from './officeShared'

export function PerimeterExport({ companyId, title, columns, rows }: {
  companyId: string
  /** Имя листа и то, что попадёт в журнал действий. */
  title: string
  columns: { header: string; key: string; width: number; money?: boolean }[]
  rows: object[]
}) {
  // Пустую таблицу выгружать нечем: файл из одних заголовков выглядит поломкой.
  if (!rows.length) return null
  return (
    <ExportButton onClick={() => {
      exportTable(title, columns, rows)
      logExport(companyId, title, rows.length)
    }} />
  )
}

/** Чем подтверждён расчёт: одна подача на продукт — цветная точка и текст рядом. */
export const CONF_TONE: Record<string, string> = {
  document: 'bg-emerald-500',
  message: 'bg-sky-500',
  witness: 'bg-amber-500',
  spoken: 'bg-muted-foreground/40',
}
