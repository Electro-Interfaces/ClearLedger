/**
 * «Магазин» → Каталог → Здоровье каталога.
 *
 * Не витрина, а список работы. Замер 04.08.2026 показал, чем справочник был на
 * самом деле: 7 547 карточек, у всех пустой класс SKU, ни одного признака
 * блюда при 32 живых рецептурах, у 76% нет штрихкода. Пока это не видно
 * цифрой, каталог выглядит наполненным — и никто не занимается им, пока с АЗС
 * не позвонят «товар есть, пробить нельзя».
 *
 * Метрики считаются по ЖИВОМУ ассортименту отдельно от всего справочника:
 * шеститысячный архив хоронит любой показатель. «Фото нет у 7 500 карточек»
 * звучит безнадёжно, «нет у 865 торгуемых» — это работа на неделю.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HeartPulse, AlertTriangle, Boxes, Check, X } from 'lucide-react'
import {
  decideCatalogEnrichment, getCatalogEnrichment, getCatalogHealth,
  type EnrichmentValue,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

/** Полоса заполненности: доля карточек, у которых поле есть. */
function Полоса({ пусто, всего }: { пусто: number; всего: number }) {
  const доля = всего > 0 ? Math.round(((всего - пусто) / всего) * 100) : 0
  const цвет = доля >= 80 ? 'bg-emerald-500' : доля >= 40 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div className={`h-full ${цвет}`} style={{ width: `${доля}%` }} />
    </div>
  )
}

function Плитка({ label, пусто, всего, hint }: {
  label: string; пусто: number; всего: number; hint?: string
}) {
  const доля = всего > 0 ? Math.round(((всего - пусто) / всего) * 100) : 0
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{доля}%</span>
        <span className="text-xs text-muted-foreground">
          не заполнено у {пусто.toLocaleString('ru-RU')}
        </span>
      </div>
      <Полоса пусто={пусто} всего={всего} />
      {hint && <div className="mt-2 text-xs leading-relaxed text-muted-foreground">{hint}</div>}
    </div>
  )
}

function Дефект({ label, значение, hint, критично }: {
  label: string; значение: number; hint: string; критично?: boolean
}) {
  const тихо = значение === 0
  return (
    <div className={`rounded-lg border p-4 ${тихо ? 'border-border' : критично
      ? 'border-red-500/40 bg-red-500/5' : 'border-amber-500/40 bg-amber-500/5'}`}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {!тихо && <AlertTriangle className={`h-3.5 w-3.5 ${критично ? 'text-red-500' : 'text-amber-500'}`} />}
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">
        {значение.toLocaleString('ru-RU')}
      </div>
      <div className="mt-2 text-xs leading-relaxed text-muted-foreground">{hint}</div>
    </div>
  )
}

/**
 * Разбор предложений: одна строка — одна марка, а не одна карточка.
 *
 * Подтверждать «Winston» двадцать три раза подряд — работа ни о чём: решение
 * принимается один раз на марку и применяется ко всем её позициям. Примеры
 * названий показаны рядом, чтобы решение принималось по товару, а не по слову.
 */
function МаркаНаРешение({ значение, onРешить, занят }: {
  значение: EnrichmentValue
  onРешить: (ids: number[], принять: boolean) => void
  занят: boolean
}) {
  return (
    <div className="flex items-start gap-3 border-b border-border py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-medium">{значение.value}</span>
          <span className="text-xs text-muted-foreground">
            {значение.позиций.toLocaleString('ru-RU')}&nbsp;позиций
          </span>
        </div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">
          {значение.примеры.join(' · ')}
        </div>
      </div>
      <div className="flex shrink-0 gap-1">
        <button type="button" disabled={занят}
                onClick={() => onРешить(значение.ids, true)}
                className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 px-2.5 py-1
                           text-xs text-emerald-500 hover:bg-emerald-500/10 disabled:opacity-50">
          <Check className="h-3.5 w-3.5" />Это бренд
        </button>
        <button type="button" disabled={занят}
                onClick={() => onРешить(значение.ids, false)}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1
                           text-xs text-muted-foreground hover:bg-muted disabled:opacity-50">
          <X className="h-3.5 w-3.5" />Нет
        </button>
      </div>
    </div>
  )
}

function БрендыНаПодтверждение() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [показатьВсе, setПоказатьВсе] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['catalog-enrichment', 'brand', company.id],
    queryFn: () => getCatalogEnrichment('brand'),
  })
  const решение = useMutation({
    mutationFn: ({ ids, принять }: { ids: number[]; принять: boolean }) =>
      decideCatalogEnrichment(ids, принять),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['catalog-enrichment', 'brand', company.id] })
      qc.invalidateQueries({ queryKey: ['catalog-health', company.id] })
    },
  })

  if (isLoading) return null
  if (!data || !data.значения.length) return null

  const видимые = показатьВсе ? data.значения : data.значения.slice(0, 12)
  return (
    <div>
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Бренды на подтверждение
      </div>
      <div className="rounded-lg border border-border px-4 py-1">
        <p className="border-b border-border py-3 text-xs leading-relaxed text-muted-foreground">
          Марки вынуты из наименований товара — то, что написано на карточке, а не
          придумано. Подтверждённое значение ложится в справочник и уезжает на
          станции обычным обновлением. Ждут решения{' '}
          {data.всего_предложений.toLocaleString('ru-RU')} позиций в{' '}
          {data.значения.length.toLocaleString('ru-RU')} марках.
        </p>
        {видимые.map((з) => (
          <МаркаНаРешение key={`${з.value}:${з.source}`} значение={з}
                          занят={решение.isPending}
                          onРешить={(ids, принять) => решение.mutate({ ids, принять })} />
        ))}
        {data.значения.length > видимые.length && (
          <button type="button" onClick={() => setПоказатьВсе(true)}
                  className="w-full py-3 text-xs text-muted-foreground hover:text-foreground">
            Показать все {data.значения.length} марок
          </button>
        )}
      </div>
    </div>
  )
}

// Русское числительное согласуется с числом. Строка «Ещё 1 групп архивных»
// читается как сбой отчёта, а страница здоровья и так про доверие к цифрам.
function склон(n: number, одна: string, две: string, много: string) {
  const с = Math.abs(n) % 100
  const е = с % 10
  if (с > 10 && с < 20) return много
  if (е > 1 && е < 5) return две
  if (е === 1) return одна
  return много
}

export function StoreCatalogHealthPanel() {
  const { company } = useCompany()
  const { data, isLoading, error } = useQuery({
    queryKey: ['catalog-health', company.id],
    queryFn: getCatalogHealth,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Считаем каталог…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить здоровье каталога</div>
  if (!data) return null

  const и = data.итого
  const живых = и.живых || 1

  return (
    <div className="space-y-6 p-6">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <HeartPulse className="h-4 w-4 text-primary" />Здоровье каталога
        </h3>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Чего не хватает справочнику и где он врёт. Заполненность считается по
          живому ассортименту — {и.живых.toLocaleString('ru-RU')} карточек класса
          «Сопутка» или «Блюдо», у которых есть цена станции, код кассы или
          остаток. Всего в справочнике {и.всего.toLocaleString('ru-RU')}:
          остальное — сырьё кухни, позиции без класса и архив, по которому
          история чеков есть, а на полке его нет. Архив в знаменателе процентов
          не стоит — иначе «заполнено 77 %» означало бы не то, что написано.
        </p>
      </div>

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Заполненность живого ассортимента
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Плитка label="Штрихкод" пусто={и.без_штрихкода} всего={живых}
                  hint="Без кода товар не пробьётся на кассе и не опознается при приёмке." />
          <Плитка label="Группа" пусто={(и.без_группы ?? 0) + (и.в_прочем ?? 0)} всего={живых}
                  hint={`Без группы вовсе: ${и.без_группы ?? 0}. Ещё ${и.в_прочем ?? 0} стоят в корзине «Прочее» — группа настоящая, матрица по ней работает, но отчёт по категориям о таком товаре не расскажет.`} />
          <Плитка label="Цена" пусто={и.без_цены} всего={живых}
                  hint={`Нет цены НИ НА ОДНОЙ станции. Цена станционная, поэтому смотреть надо и по АЗС: ${
                    (data.по_станциям ?? []).map((с) => `АЗС ${с.station_id} — ${с.с_ценой} с ценой`).join(', ') || 'станций нет'
                  }. Остаток без цены — товар лежит, а продать его нельзя.`} />
          <Плитка label="Бренд" пусто={и.без_бренда} всего={живых}
                  hint="Приезжает из Национального каталога по GTIN и из накладных ЭДО." />
          <Плитка label="Состав" пусто={и.без_состава} всего={живых}
                  hint="То, что спрашивает покупатель и требует проверка по общепиту." />
          <Плитка label="Фото" пусто={и.без_фото} всего={живых}
                  hint="Опознание товара при приёмке и пересчёте: имя в мастер-каталоге может расходиться с этикеткой." />
        </div>
      </div>

      <БрендыНаПодтверждение />

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Дефекты — это работа, а не статистика
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Дефект label="Коллизии штрихкодов" значение={и.коллизии_шк} критично
                  hint={`Один код активен у двух карточек одного яруса: касса продаёт ту, что выгрузилась последней. Ноль здесь — не удача, а устройство справочника: активный код держит уникальный индекс, второй карточке он просто не достаётся. Отдельно ${и.привязок_отклонено ?? 0} ${склон(и.привязок_отклонено ?? 0, 'привязка отклонена', 'привязки отклонены', 'привязок отклонено')} центром — там код уже работал у другой карточки: сработавшая защита, а не авария. Цена защиты — та карточка осталась без кода и не пробивается.`} />
          <Дефект label="GTIN не добыть из кода" значение={(и.маркируемые_без_gtin ?? 0) - (и.gtin_из_шк ?? 0)} критично
                  hint={`GTIN нет ни у одной из ${и.маркируемых_всего ?? 0} маркируемых позиций. Но добывать его надо не для всех: у ${и.gtin_из_шк ?? 0} он и есть собственный штрихкод — это перенос одной командой. В цифре плитки те, у кого нет ни GTIN, ни кода нужной длины: только их придётся искать в Национальном каталоге.`} />
          <Дефект label="Блюдо помечено маркируемым" значение={и.блюда_маркируемые ?? 0}
                  hint="У готовой еды DataMatrix не бывает: признак ошибочный. Он раздувает работу по GTIN и уезжает в кассу свойством товара." />
          <Дефект label="Табак без МРЦ" значение={и.табак_без_мрц} критично
                  hint={`Сигареты и стики: продажа выше максимальной цены — нарушение ст. 13 ФЗ-15. Аксессуары (зажигалки, портсигары) сюда не входят — МРЦ у них нет. Нарушают на конкретной АЗС, поэтому смотреть по станциям: ${
                    (data.мрц_по_станциям ?? []).map((с) => `АЗС ${с.station_id} — ${с.без_мрц}`).join(', ') || 'ни одной'
                  }.`} />
          <Дефект label="Блюдо без ТТК на станции" значение={и.блюда_без_ттк} критично
                  hint={`Блюдо стоит в кассе, применяется — и продажа не списывает сырьё: кофе продан, зерно на остатке. Всего блюд без действующей карты ${и.блюда_без_ттк_всего ?? 0}, но остальные продать сейчас нельзя: станция не запущена либо позиция закрыта матрицей.`} />
          <Дефект label="Устаревшая ставка НДС" значение={и.ставка_устарела}
                  hint={`18/118 и 20% в карточках: смена уедет в бухгалтерию с неверным налогом. Цифра по живому ассортименту, как и всё на этой странице; по всему справочнику вместе с архивом — ${и.ставка_устарела_всего ?? и.ставка_устарела}.`} />
          <Дефект label="Тёзки: живые пары" значение={data.дубли.живых_пар}
                  hint={`Обе карточки чем-то заняты — штрихкодом, ценой или кодом кассы: сводный отчёт по такой паре не сойдётся. Архивных ${склон(data.дубли.архивных, 'группа', 'группы', 'групп')}: ${data.дубли.архивных} (товара за ними нет, сводить нечего). Всего групп ${data.дубли.групп}, лишних карточек ${data.дубли.лишних}. Разбор по видам — «Товар и станции» → «Тёзки»: большая часть пар это наследие 1С и ассортимент под общим именем, а не дубли.`} />
          <Дефект label="Без класса SKU" значение={и.без_класса}
                  hint="Сопутка, сырьё и блюдо неразличимы — любой отчёт по общепиту врёт." />
          <Дефект label="Марки на подтверждение" значение={и.предложений_ждёт}
                  hint="Это те же марки, что в блоке «Бренды на подтверждение» выше: вынуты из наименований нашим разбором, а не присланы извне. В справочник попадают только подтверждённые человеком." />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <Boxes className="h-3.5 w-3.5" />Классы SKU
          </div>
          <table className="w-full text-sm">
            <tbody>
              {data.по_классам.map((k) => (
                <tr key={k.класс} className="border-b border-border/50">
                  <td className="py-1.5">{k.класс}</td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                    {k.карточек.toLocaleString('ru-RU')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Группы: всего / из них торгуются
          </div>
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {data.по_группам.filter((g) => g.карточек > 0).map((g) => (
                  <tr key={g.path} className="border-b border-border/50">
                    <td className="py-1.5">{g.path}</td>
                    <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                      {g.карточек.toLocaleString('ru-RU')}
                    </td>
                    <td className="w-16 py-1.5 text-right tabular-nums">
                      {g.живых > 0 ? g.живых.toLocaleString('ru-RU') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
