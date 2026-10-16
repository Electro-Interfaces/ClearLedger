/**
 * Куски экранов с черновиком: плашка «черновик / действует», итог проверки с
 * формой «Применить», строка формы и поле числа.
 */
import { useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, GitBranch, History, Info, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type * as voice from '@/services/voiceService'
import { когда, время } from './format'
import type { Черновик } from './useDraft'

// ——— Плашка черновика ———

function кто(a?: voice.Actor | null) {
  return a?.name ?? (a?.kind === 'node' ? 'узел' : a?.sub ?? 'неизвестно')
}

const полей = (n: number) => {
  const m10 = n % 10, m100 = n % 100
  return m10 === 1 && m100 !== 11 ? 'поле' : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? 'поля' : 'полей'
}

/**
 * Прилипает к верху экрана: что сейчас действует или что в черновике, и три действия.
 * На телефоне — одна строка, подробности уходят.
 */
export function DraftBar<B>({ ч, примечание }: { ч: Черновик<B>; примечание?: ReactNode }) {
  const [отмена, setОтмена] = useState(false)
  const есть = !!ч.черновик || ч.изменено.length > 0
  const a = ч.действующая
  const номер = ч.черновик?.version ?? (a ? a.version + 1 : undefined)
  const проверен = ч.черновик?.state === 'validated' && ч.сохранение !== 'saving' && ч.сохранение !== 'error'

  if (!есть) {
    return (
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-3 shadow-sm">
        <CheckCircle2 className="hidden h-5 w-5 shrink-0 text-success sm:block" />
        <div className="min-w-0 flex-1 text-sm">
          <p><span className="font-medium">Действует r{a?.version}</span>
            {a?.appliedAt && <span className="text-muted-foreground"> · применена {когда(a.appliedAt)} · {кто(a.appliedBy)}</span>}</p>
          <p className="hidden text-xs text-muted-foreground sm:block">
            Изменение любого поля создаст черновик r{номер}; действующие настройки не меняются до «Применить».
          </p>
        </div>
        <Button asChild variant="outline" size="sm"><Link to="/voice/versions"><History />Версии</Link></Button>
      </div>
    )
  }

  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-primary/35 bg-card p-3 shadow-sm"
      style={{ backgroundImage: 'linear-gradient(hsl(var(--primary) / .07), hsl(var(--primary) / .07))' }}>
      <GitBranch className="hidden h-5 w-5 shrink-0 text-primary sm:block" />
      <div className="min-w-0 flex-1 text-sm">
        <p>
          <span className="font-medium">Черновик r{номер}</span>
          <span className="text-muted-foreground"> · изменено {ч.изменено.length} {полей(ч.изменено.length)} от действующей r{a?.version}</span>
        </p>
        <p className="hidden text-xs text-muted-foreground sm:block">
          {ч.сохранение === 'saving' ? 'Сохраняем…'
            : ч.сохранение === 'error' ? <span className="text-destructive">Не сохранено — правка на экране, повторим со следующей</span>
            : ч.сохраненоВ ? `Сохранено ${время(ч.сохраненоВ.toISOString())}`
            : ч.черновик ? `Начат ${когда(ч.черновик.createdAt)} · ${кто(ч.черновик.createdBy)}` : 'Сохраняем…'}
          {' · '}{проверен ? 'проверен' : 'не проверен'}
          {примечание && <> · {примечание}</>}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {отмена ? (
          <>
            <span className="text-xs">Удалить черновик r{номер}?</span>
            <Button variant="destructive" size="sm" onClick={() => { setОтмена(false); void ч.отменить() }}>Удалить</Button>
            <Button variant="ghost" size="sm" onClick={() => setОтмена(false)}>Нет</Button>
          </>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setОтмена(true)}>Отменить черновик</Button>
        )}
        <Button variant="outline" size="sm" onClick={() => void ч.проверить()} disabled={ч.проверяем}>
          <CheckCircle2 />{ч.проверяем ? 'Проверяем…' : 'Проверить'}
        </Button>
      </div>
    </div>
  )
}

// ——— Итог проверки и применение ———

const КОД_ПРОВЕРКИ: Record<string, string> = {
  invalid: 'поле заполнено неверно',
  schema: 'не проходит схему',
  range: 'значение вне допустимого',
  target_missing: 'цель не настроена у узла',
  target_mismatch: 'списки целей расходятся',
  restart_required: 'меняется только перезапуском узла',
  offer_after_fallback: 'предложение перезвонить не успеет прозвучать',
  sound_missing: 'звук не загружен',
}

/**
 * Итог проверки словами: ошибки блокируют, предупреждения нет. Ниже — последствия
 * (перезапуск, новая версия паспорта для КЦ) и форма «Применить» с комментарием.
 */
export function CheckResult<B>({ ч, подписи, последствия, подтверждение }: {
  ч: Черновик<B>
  /** путь поля (JSON Pointer) → подпись на экране */
  подписи: Record<string, string>
  /** что произойдёт при применении: строки словами */
  последствия: ReactNode[]
  /** если задано — перед применением нужна галка (ломающее изменение паспорта) */
  подтверждение?: string
}) {
  const [зачем, setЗачем] = useState('')
  const [согласен, setСогласен] = useState(false)
  const п = ч.проверка
  if (!п) return null
  const ошибки = п.issues.filter(i => i.level !== 'warning')
  const предупреждения = п.issues.filter(i => i.level === 'warning')
  const можно = п.ok && ч.черновик?.state === 'validated' && зачем.trim().length >= 3 && (!подтверждение || согласен)

  const подпись = (path: string) => {
    const точная = подписи[path]
    if (точная) return точная
    const родитель = Object.keys(подписи).filter(k => path.startsWith(`${k}/`)).sort((x, y) => y.length - x.length)[0]
    return родитель ? подписи[родитель] : null
  }

  return (
    <section aria-label="Итог проверки" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="font-headline text-base font-semibold">Проверка черновика r{ч.черновик?.version}</h2>
        <span className="text-xs text-muted-foreground">
          {ошибки.length} ошиб{ошибки.length === 1 ? 'ка' : ошибки.length >= 2 && ошибки.length <= 4 ? 'ки' : 'ок'}
          {' · '}{предупреждения.length} предупрежд{предупреждения.length === 1 ? 'ение' : предупреждения.length >= 2 && предупреждения.length <= 4 ? 'ения' : 'ений'}
        </span>
      </div>
      {п.ok && !п.issues.length && (
        <p className="flex items-start gap-2 text-sm"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
          Все поля верны, связи с паспортом и звуками сходятся.</p>
      )}
      {[...ошибки, ...предупреждения].map((i, n) => (
        <div key={`${i.path}-${i.code}-${n}`} className="flex items-start gap-2 text-sm">
          {i.level === 'warning'
            ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
          <div className="min-w-0">
            <p>
              <span className={i.level === 'warning' ? 'text-warning' : 'text-destructive'}>
                {i.level === 'warning' ? 'Предупреждение' : 'Ошибка'}
              </span>
              {': '}{подпись(i.path) ?? 'поле'} — {i.message ?? КОД_ПРОВЕРКИ[i.code] ?? i.code}
            </p>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Подробнее</summary>
              <span className="font-mono">{i.path || '/'} · {i.code}</span>
            </details>
          </div>
        </div>
      ))}

      {п.ok && (
        <>
          {последствия.map((x, n) => (
            <p key={n} className="flex items-start gap-2 text-sm"><Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />{x}</p>
          ))}
          {подтверждение && (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={согласен} onChange={e => setСогласен(e.target.checked)} className="mt-1" />
              {подтверждение}
            </label>
          )}
          <form className="flex flex-wrap items-center gap-2 pt-1"
            onSubmit={async e => { e.preventDefault(); if (можно && await ч.применить(зачем.trim())) setЗачем('') }}>
            <Input value={зачем} onChange={e => setЗачем(e.target.value)} maxLength={500}
              aria-label="Зачем меняем" placeholder="Зачем меняем — попадёт в журнал изменений" className="min-w-60 flex-1" />
            <Button type="submit" disabled={!можно || ч.применяем}>
              <CheckCircle2 />{ч.применяем ? 'Применяем…' : `Применить r${ч.черновик?.version}`}
            </Button>
          </form>
          {ч.черновик?.state !== 'validated' && (
            <p className="text-xs text-muted-foreground">Черновик изменён после проверки — проверьте снова.</p>
          )}
        </>
      )}
      {!п.ok && <p className="text-xs text-muted-foreground">Исправьте ошибки и проверьте снова. Работают прежние настройки.</p>}
    </section>
  )
}

// ——— Поле формы ———

/** Строка формы: подпись с пояснением слева, управление справа, «было …» у изменённого. */
export function Field({ имя, подсказка, было, children, className }: {
  имя: string
  подсказка?: ReactNode
  было?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('grid gap-1.5 border-b border-border/60 py-3 last:border-0 md:grid-cols-[minmax(0,18rem)_1fr] md:gap-4', className)}>
      <div className="min-w-0">
        <p className="text-sm font-medium">{имя}</p>
        {подсказка && <p className="text-xs text-muted-foreground">{подсказка}</p>}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {children}
        {было !== undefined && <span className="text-xs text-primary">изменено · было {было}</span>}
      </div>
    </div>
  )
}

/** Число с единицей; пусто — значение по умолчанию узла (подсказкой в поле). */
export function NumberInput({ значение, onChange, единица, поУмолчанию, подпись, целое = true, min = 0 }: {
  значение: number | undefined
  onChange: (v: number | undefined) => void
  единица?: string
  поУмолчанию?: number
  подпись: string
  целое?: boolean
  min?: number
}) {
  const [текст, setТекст] = useState(значение === undefined ? '' : String(значение))
  // Значение сменилось снаружи (откат правки, чужой черновик) — показываем его; своё набранное «5.» не трогаем.
  const [прежнее, setПрежнее] = useState(значение)
  if (прежнее !== значение) {
    setПрежнее(значение)
    if ((текст.trim() === '' ? undefined : Number(текст.replace(',', '.'))) !== значение) {
      setТекст(значение === undefined ? '' : String(значение))
    }
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <Input value={текст} inputMode={целое ? 'numeric' : 'decimal'} aria-label={подпись}
        placeholder={поУмолчанию !== undefined ? String(поУмолчанию) : undefined}
        className="h-9 w-24 text-right font-mono tabular-nums"
        onChange={e => {
          const t = e.target.value.replace(',', '.')
          setТекст(t)
          if (t.trim() === '') { onChange(undefined); return }
          const n = Number(t)
          if (Number.isFinite(n) && n >= min && (!целое || Number.isInteger(n))) onChange(n)
        }} />
      {единица && <span className="text-sm text-muted-foreground">{единица}</span>}
      {поУмолчанию !== undefined && значение === undefined && (
        <span className="text-xs text-muted-foreground">по умолчанию</span>
      )}
    </span>
  )
}
