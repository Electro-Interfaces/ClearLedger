/**
 * «Магазин» → Касса → Не доехало в кассу.
 *
 * Монитор доставки справочника, а не действие. Центр в кассу не пишет никогда:
 * короткий файл и полный перелив делает агент на станции. Здесь видно, где
 * товар лежит на полке, а касса отвечает «мало товара», — и откуда перейти на
 * рабочее место, чтобы это починить.
 *
 * Три разные беды, и лечатся они по-разному:
 *   · канал встал — очередь наверх копится, справочник отстаёт;
 *   · остатки разошлись — касса выше учёта (разбор) или ниже (окно разнесения);
 *   · карточка не уедет вовсе — нет штрихкода или кода кассы. Такую позицию
 *     не спасёт ни один файл, пока реквизит не заполнят.
 */
import { useQuery } from '@tanstack/react-query'
import { CloudOff, AlertTriangle, ArrowRight } from 'lucide-react'
import { getStoreCashSync, type StoreCashSyncStation } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

function когда(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Насколько давно станция выходила на связь. Час молчания — уже вопрос. */
function отставание(iso: string | null | undefined): { текст: string; тревога: boolean } {
  if (!iso) return { текст: 'связи не было', тревога: true }
  const минут = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutesInvalid(минут)) return { текст: '—', тревога: false }
  if (минут < 5) return { текст: 'на связи', тревога: false }
  if (минут < 60) return { текст: `${минут} мин назад`, тревога: false }
  const часов = Math.round(минут / 60)
  return { текст: `${часов} ч назад`, тревога: часов >= 2 }
}
function minutesInvalid(n: number) { return Number.isNaN(n) || n < 0 }

function Цифра({ label, значение, тревога, hint }: {
  label: string; значение: number | null; тревога?: boolean; hint?: string
}) {
  return (
    <div title={hint} className="min-w-[92px]">
      <div className={`text-xl font-semibold tabular-nums ${тревога && (значение ?? 0) > 0 ? 'text-red-300' : ''}`}>
        {значение ?? '—'}
      </div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  )
}

export function StoreCashSyncPanel() {
  const { company } = useCompany()
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-cash-sync', company.id],
    queryFn: getStoreCashSync,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка канала…</div>
  if (error) {
    return <div className="p-6 text-sm text-destructive">Не удалось загрузить: {(error as Error).message}</div>
  }
  const станции = data?.stations ?? []

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary shrink-0">
          <CloudOff className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Канал справочника в кассу</h3>
          <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
            Где касса отстала от учёта. Правит справочник станция — центр в кассу не
            пишет никогда. Здесь видно, что именно мешает: встал канал, разошлись
            остатки или карточке нечем уехать.
          </p>
        </div>
      </div>

      {станции.length === 0 && (
        <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
          Ни одной станции.
        </div>
      )}

      {станции.map((с: StoreCashSyncStation) => {
        const связь = отставание(с.last_seen)
        const немое = !с.cash_ok
        const нечемУехать = (с.без_штрихкода ?? 0) + (с.без_кода_кассы ?? 0)
        return (
          <div key={с.station_id} className="rounded-lg border bg-card p-4 space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="font-medium">{с.name}</div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="font-mono">{с.version ?? 'версия неизвестна'}</span>
                <span className={связь.тревога ? 'text-red-300' : ''}>{связь.текст}</span>
              </div>
            </div>

            {немое && (
              <div className="flex gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-2.5 text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                <div className="text-muted-foreground">
                  Канал кассы не отвечает: агент не смог прочитать справочник поста. Пока это
                  так, ни цена, ни приход в кассу не уедут — и станция об этом не узнает.
                </div>
              </div>
            )}

            {/* Очередь наверх. Пакет, который центр отвергает раз за разом, висит
                вечно и прячет собой настоящий сбой — для него есть agent outbox-stuck. */}
            <div>
              <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Очередь и отставание
              </div>
              <div className="flex flex-wrap gap-x-8 gap-y-3">
                <Цифра label="в очереди" значение={с.queue_pending}
                       hint="Пакеты станции, ещё не принятые центром" />
                <Цифра label="с ошибкой" значение={с.queue_failing} тревога
                       hint="Центр отвергает раз за разом. Повтор лечит не всякую ошибку: «уже принят» и «ждёт разбора» отпускают командой agent outbox-stuck" />
                <div className="min-w-[150px]">
                  <div className="text-sm tabular-nums">{когда(с.last_sent_at)}</div>
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">последняя отправка</div>
                </div>
                <div className="min-w-[150px]">
                  <div className="text-sm tabular-nums">{когда(с.checked_at)}</div>
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">снимок сверки</div>
                </div>
              </div>
            </div>

            {/* Витрина станции против справочника поста. Читается по НАПРАВЛЕНИЮ:
                выше — разбор, ниже — окно разнесения, уйдёт само за такт. */}
            <div>
              <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Витрина станции против справочника поста
              </div>
              <div className="flex flex-wrap gap-x-8 gap-y-3">
                <Цифра label="в кассе" значение={с.in_cash} />
                <Цифра label="должно быть" значение={с.should_be} />
                <Цифра label="совпало" значение={с.matched} />
                <Цифра label="касса выше" значение={с.above} тревога
                       hint="Разбор обязателен: продажи касса вычитает сама, приход мы досылаем — превышение штатным не бывает" />
                <Цифра label="касса ниже" значение={с.below}
                       hint="Окно разнесения: чек уже пробит, а мы узнаем о нём ближайшим тактом. Уйдёт само" />
                <Цифра label="строк без карточки" значение={с.no_card}
                       hint="Строки справочника поста, которых нет у нас: чужой товар, топливо, услуги" />
              </div>
            </div>

            {/* Карточка без реквизита не уедет никаким файлом. Это не доставка,
                а справочник: пока не заполнят, товар на полке не пробивается. */}
            <div>
              <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Карточки, которым нечем уехать
              </div>
              <div className="flex flex-wrap gap-x-8 gap-y-3">
                <Цифра label="позиций станции" значение={с.позиций} />
                <Цифра label="без штрихкода" значение={с.без_штрихкода} тревога
                       hint="Ни один файл такую карточку не довезёт: касса ищет товар по штрихкоду" />
                <Цифра label="без цены" значение={с.без_цены} тревога
                       hint="Товар лежит, а продать его нельзя" />
                <Цифра label="без кода кассы" значение={с.без_кода_кассы} тревога
                       hint="Код нефтесервера локален для станции. Нет кода — позиции в справочнике поста не существует" />
              </div>
              {нечемУехать > 0 && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  Таких позиций <b className="text-foreground">{нечемУехать}</b>. Это не беда
                  доставки: файл довезёт только то, у чего есть штрихкод и код кассы. Пока
                  реквизит не заполнен, товар лежит на полке и не пробивается.
                </p>
              )}
            </div>

            <div className="flex items-center gap-1.5 border-t pt-3 text-xs text-muted-foreground">
              <ArrowRight className="h-3.5 w-3.5 shrink-0" />
              Перелить справочник целиком можно только на агенте АЗС — вход в рабочее
              место станции в разделе «Станции» → «Сеть одним взглядом».
            </div>
          </div>
        )
      })}

      {data?.заявки_на_перелив == null && (
        <div className="rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
          <b className="text-foreground">Заявок на перелив здесь пока нет.</b> Агент сам
          заказывает полный перелив, когда наткнётся на хвост в кассе, — но в телеметрию
          это не попадает: такого поля в пакете нет. Чтобы сигнал доходил до центра, его
          надо добавить в агента; выдумывать цифру вместо него мы не станем.
        </div>
      )}
    </div>
  )
}
