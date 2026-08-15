/**
 * «Периметр» → «Настройки» — что компания включает себе сама.
 *
 * Продукт закрывает разные по чувствительности вещи: арендованный склад на 001 —
 * обычный учёт, а доплата сверх ведомости — то, за что отвечают лично. Поэтому спорные
 * возможности выключены по умолчанию, включаются осознанно и с предупреждением, а
 * решение остаётся в журнале действий: кто включил и когда.
 *
 * Пороговые значения тоже здесь, а не в коде: срок отчёта по подотчёту компания
 * устанавливает сама, лимит наличных и сроки давности могут меняться. Зашитая
 * константа была бы чужим решением, выданным за истину.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  getPerimeterSettings, savePerimeterSettings, type PerimeterSettings,
} from '@/services/perimeterService'
import { Loading } from './OfficePanels'

const inputCls = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'

function Row({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[1fr_10rem] sm:items-start py-3 border-b last:border-0">
      <div>
        <div className="text-sm">{label}</div>
        {hint && <div className="text-[11px] text-muted-foreground mt-0.5">{hint}</div>}
      </div>
      <div>{children}</div>
    </div>
  )
}

export function PerimeterSettingsScreen({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['perimeter', 'settings', companyId],
    queryFn: () => getPerimeterSettings(companyId),
    enabled: !!companyId,
  })
  const [form, setForm] = useState<PerimeterSettings | null>(null)
  useEffect(() => { if (q.data) setForm(q.data) }, [q.data])

  const save = useMutation({
    mutationFn: (v: PerimeterSettings) => savePerimeterSettings(companyId, {
      allowExtraPay: v.allowExtraPay, advanceDays: v.advanceDays,
      cashLimit: v.cashLimit, loanWrittenFrom: v.loanWrittenFrom,
      loanInterestFrom: v.loanInterestFrom, limitationYears: v.limitationYears,
      showDisclaimer: v.showDisclaimer,
    }),
    onSuccess: () => {
      toast.success('Настройки сохранены')
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить настройки" onRetry={() => q.refetch()} />
    </div>
  }
  if (!form) return <Loading />
  const set = (patch: Partial<PerimeterSettings>) => setForm({ ...form, ...patch })
  const num = (v: string) => (v === '' ? 0 : Number(v))

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-base font-medium">Возможности</div>

          <Row label="Доплаты сверх ведомости"
            hint="Выплаты работникам помимо расчётного листка, из средств собственника. Пока выключено, такого вида в журнале нет вовсе.">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.allowExtraPay}
                onChange={(e) => set({ allowExtraPay: e.target.checked })} />
              {form.allowExtraPay ? 'включено' : 'выключено'}
            </label>
          </Row>

          {form.allowExtraPay && (
            <div className="rounded-md border border-amber-500/50 bg-amber-500/5 p-3
                text-[11px] text-muted-foreground space-y-1.5">
              <div className="text-sm text-amber-700 dark:text-amber-500">
                Что стоит понимать, включая это
              </div>
              <p>
                Запись такой выплаты не уменьшает обязательств компании перед работником
                и бюджетом: НДФЛ и страховые взносы начисляются на весь доход, независимо
                от того, как он выплачен. Продукт помогает знать реальные расчёты — он не
                заменяет оформление и не защищает от последствий.
              </p>
              <p>
                Сам реестр — сильное доказательство: он структурирован, датирован и
                поимённый. Держите доступ к разделу узким, а выгрузки — под контролем;
                каждая из них попадает в журнал действий пространства.
              </p>
              <p>
                Правильный ход, если такие выплаты есть: постепенно переводить их в
                оформленные — договором подряда, премией по приказу, компенсацией
                расходов. Записи «Периметра» показывают объём, с которым предстоит
                работать.
              </p>
            </div>
          )}

          <Row label="Оговорка о статусе данных"
            hint="Показывать на экранах и в выгрузках: «оперативная запись руководителя, не документ бухгалтерского учёта». Снимает риск, что цифры примут за учётные.">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.showDisclaimer}
                onChange={(e) => set({ showDisclaimer: e.target.checked })} />
              {form.showDisclaimer ? 'показывать' : 'скрыть'}
            </label>
          </Row>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 space-y-1">
          <div className="text-base font-medium">Сроки и пороги</div>
          <p className="text-[11px] text-muted-foreground pb-2">
            По этим числам продукт предупреждает на форме и считает просрочку. Значения
            по умолчанию взяты из общих правил, но компания вправе установить свои.
          </p>

          <Row label="Срок отчёта по подотчёту, дней"
            hint="Устанавливает работодатель. Невозвращённое и неотчитанное после срока налоговая признаёт доходом человека с НДФЛ и взносами.">
            <input className={inputCls} type="number" min="1" max="365"
              value={form.advanceDays}
              onChange={(e) => set({ advanceDays: num(e.target.value) })} />
          </Row>

          <Row label="Предел наличного расчёта, ₽"
            hint="Между организациями и ИП по одному договору. Превышение — нарушение кассовой дисциплины.">
            <input className={inputCls} type="number" min="0" step="1000"
              value={form.cashLimit}
              onChange={(e) => set({ cashLimit: num(e.target.value) })} />
          </Row>

          <Row label="Заём требует расписки от, ₽"
            hint="Выше этой суммы заём между гражданами должен быть письменным: без бумаги в споре нельзя ссылаться на свидетелей, только на письменные доказательства.">
            <input className={inputCls} type="number" min="0" step="1000"
              value={form.loanWrittenFrom}
              onChange={(e) => set({ loanWrittenFrom: num(e.target.value) })} />
          </Row>

          <Row label="Заём считается процентным от, ₽"
            hint="Выше этой суммы заём по умолчанию процентный по ключевой ставке. Если договорились без процентов, это нужно прямо написать в расписке.">
            <input className={inputCls} type="number" min="0" step="10000"
              value={form.loanInterestFrom}
              onChange={(e) => set({ loanInterestFrom: num(e.target.value) })} />
          </Row>

          <Row label="Срок исковой давности, лет"
            hint="Общий срок — три года. Он прерывается признанием долга: частичной оплатой, актом сверки, просьбой об отсрочке — и течёт заново.">
            <input className={inputCls} type="number" min="1" max="10"
              value={form.limitationYears}
              onChange={(e) => set({ limitationYears: num(e.target.value) })} />
          </Row>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">
          {form.updatedAt ? `Изменено ${form.updatedAt.slice(0, 10)}` : ''}
        </span>
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate(form)}>
          {save.isPending ? 'Сохраняем…' : 'Сохранить'}
        </Button>
      </div>
    </div>
  )
}
