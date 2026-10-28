/**
 * Что считать работой по проекту: состав плана, группы по датам и видимый шаг.
 *
 * Логика вынесена из панелей, потому что на ней разошлись два экрана одного
 * приложения: реестр «Проекты» считал в работе 244 проекта, а «План работ» —
 * 343, причём один проект стоял в списке дважды (проверка 25.10.2026). Группы
 * плана обязаны быть взаимоисключающими, а состав — тем же, что в реестре.
 */

/** Стадии живой воронки: те же, что показывает реестр «Все проекты». */
export const WORK_STAGES = [
  'lead', 'screening', 'negotiation', 'dd', 'decision',
  'contracting', 'construction', 'commissioning', 'live',
] as const

export interface PlanRow {
  stage: string
  kind?: string | null
  closedOn?: string | null
  nextAction?: string | null
  nextActionDue?: string | null
}

/** Строка реестра: шаг и срок приходят с сервера, ручное поле — запасной вариант. */
export interface StepRow {
  nextStep?: string | null
  nextStepDue?: string | null
  nextAction?: string | null
  nextActionDue?: string | null
}

/** Видимый шаг строки: ручной, связанная работа или внешнее ожидание. */
export const nextStepText = (r: StepRow): string | null => r.nextStep ?? r.nextAction ?? null
/** Срок видимого шага — из того же источника, что и текст. */
export const nextStepDue = (r: StepRow): string | null => r.nextStepDue ?? r.nextActionDue ?? null

/**
 * Проект в работе: живая стадия, не закрыт, не интеграция.
 *
 * Заморозка и архив — это решение не работать, их планировать нечего; проекты
 * интеграции ведутся своим разделом со своим маршрутом.
 */
export const inWork = (p: PlanRow): boolean =>
  (WORK_STAGES as readonly string[]).includes(p.stage) && !p.closedOn && p.kind !== 'integration'

export interface PlanBucket<T> { key: string; label: string; hint: string; alarm?: boolean; items: T[] }

/**
 * Раскладка плана по датам. Каждая строка попадает ровно в одну группу:
 * сначала по сроку, и только строка без срока — в «шаг есть, срока нет» или
 * «шаг не назначен».
 */
export function planBuckets<T extends PlanRow>(rows: T[], today: string, weekEnd: string): PlanBucket<T>[] {
  const has = (p: T) => !!(p.nextAction ?? '').trim()
  const due = (p: T) => p.nextActionDue || null
  const pick = (fn: (p: T) => boolean) =>
    rows.filter(fn).sort((a, b) => (due(a) ?? '9999').localeCompare(due(b) ?? '9999'))

  return [
    {
      key: 'overdue', label: 'Просрочено', alarm: true,
      hint: 'Срок шага прошёл — либо делаем, либо переносим дату честно',
      items: pick((p) => !!due(p) && due(p)! < today),
    },
    {
      key: 'today', label: 'Сегодня', hint: 'Сегодняшний срок',
      items: pick((p) => due(p) === today),
    },
    {
      key: 'week', label: 'Ближайшая неделя', hint: 'Следующие семь дней',
      items: pick((p) => !!due(p) && due(p)! > today && due(p)! <= weekEnd),
    },
    {
      key: 'later', label: 'Дальше', hint: 'Запланировано за горизонтом недели',
      items: pick((p) => !!due(p) && due(p)! > weekEnd),
    },
    {
      key: 'nodate', label: 'Шаг есть, срока нет',
      hint: 'Работа названа, но не поставлена в план — по ней нельзя спросить',
      items: pick((p) => has(p) && !due(p)),
    },
    {
      // Срок без текста шага уже показан в своей дате выше: второй раз строку
      // показывать нельзя, иначе счётчик больше числа проектов.
      key: 'nostep', label: 'Шаг не назначен',
      hint: 'Проект в работе, а что делать дальше — не записано',
      items: pick((p) => !has(p) && !due(p)),
    },
  ].filter((b) => b.items.length > 0)
}
