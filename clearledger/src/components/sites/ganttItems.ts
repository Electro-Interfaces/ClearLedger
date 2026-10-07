/**
 * Подэтапы стадии на Ганте — пункты её чек-листа (МАГ 07.10.2026: «критичные пункты
 * чек-листа тоже можно рассматривать как подэтапы»). Общий построитель для интеграции
 * и станций: у обоих пункт знает выполнен ли, критичен ли, когда и кем подтверждён.
 *
 * Полоса пункта — от входа в стадию до подтверждения. Подтверждённый заранее (до входа
 * в стадию) — только ромб. Открытый пункт текущей стадии — пунктир до «сейчас».
 * Сроков у пунктов нет: плановые даты из проектов убраны.
 */
import type { GanttRow, GanttState } from './GanttChart'
import { ruDate } from './ganttTime'

export interface GanttItem {
  key?: string; label: string; done: boolean; required: boolean; waived?: boolean
  needsConfirmation?: boolean; confirmedAt?: string | null; confirmedBy?: string | null; role?: string | null
}

export function itemRows(stageKey: string, items: GanttItem[], stage: GanttState, stageStart: number | null,
  now: number, roleName: (role: string) => string, onOpen?: () => void): GanttRow[] {
  return items.map((it, i) => {
    const status = it.needsConfirmation ? 'reconfirm' as const : it.done ? 'done' as const : it.waived ? 'waived' as const : 'open' as const
    const at = it.confirmedAt ? new Date(it.confirmedAt).getTime() : null
    const segments = status === 'done' && at != null && stageStart != null && at > stageStart ? [{ start: stageStart, end: at }]
      : status === 'open' && stage === 'current' && stageStart != null ? [{ start: stageStart, end: now, dashed: true }] : []
    const state: GanttState = status === 'done' ? 'done' : status === 'open' ? (stage === 'current' ? 'current' : 'future') : 'stopped'
    const who = it.role ? roleName(it.role) : ''
    const sub = status === 'done' ? `выполнен${at != null ? ` ${ruDate(at)}` : ''}${it.confirmedBy ? ` · ${it.confirmedBy}` : ''}`
      : status === 'reconfirm' ? 'данные изменились — подтвердить заново'
        : status === 'waived' ? 'обязательность снята'
          : stage === 'done' ? 'не выполнен, стадия пройдена' : 'не выполнен'
    return {
      key: `${stageKey}:${it.key ?? i}`, label: it.key && /^\d/.test(it.key) ? `${it.key} ${it.label}` : it.label,
      sub: who ? `${sub} · ${who}` : sub, state, segments, status, required: it.required,
      blocking: status === 'reconfirm' || (status === 'open' && it.required && stage === 'current'),
      marks: at != null && status === 'done' ? [{ key: 'at', at, title: `${it.label}\nвыполнен ${new Date(at).toLocaleString('ru-RU')}${it.confirmedBy ? ` · ${it.confirmedBy}` : ''}` }] : [],
      onOpen,
    }
  })
}
