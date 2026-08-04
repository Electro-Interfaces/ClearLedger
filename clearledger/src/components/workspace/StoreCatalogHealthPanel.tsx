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
import { useQuery } from '@tanstack/react-query'
import { HeartPulse, AlertTriangle, Boxes } from 'lucide-react'
import { getCatalogHealth } from '@/services/storeService'
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
          живому ассортименту — {и.живых.toLocaleString('ru-RU')} карточек, которые
          торгуются: есть код кассы, цена или остаток. Всего в справочнике{' '}
          {и.всего.toLocaleString('ru-RU')}, остальное — архив: история чеков по
          ним есть, а на полке их нет.
        </p>
      </div>

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Заполненность живого ассортимента
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Плитка label="Штрихкод" пусто={и.без_штрихкода} всего={живых}
                  hint="Без кода товар не пробьётся на кассе и не опознается при приёмке." />
          <Плитка label="Группа" пусто={и.без_группы} всего={живых}
                  hint="Без группы не работают матрица, отчёты по категориям и правила ветки." />
          <Плитка label="Цена" пусто={и.без_цены} всего={живых}
                  hint="Остаток без цены — товар лежит, а продать его нельзя." />
          <Плитка label="Бренд" пусто={и.без_бренда} всего={живых}
                  hint="Приезжает из Национального каталога по GTIN и из накладных ЭДО." />
          <Плитка label="Состав" пусто={и.без_состава} всего={живых}
                  hint="То, что спрашивает покупатель и требует проверка по общепиту." />
          <Плитка label="Фото" пусто={и.без_фото} всего={живых}
                  hint="Опознание товара при приёмке и пересчёте: имя в 1С расходится с этикеткой." />
        </div>
      </div>

      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Дефекты — это работа, а не статистика
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Дефект label="Коллизии штрихкодов" значение={и.коллизии_шк} критично
                  hint="Один код у двух карточек: касса продаёт ту, что выгрузилась последней." />
          <Дефект label="Маркируемые без GTIN" значение={и.маркируемые_без_gtin} критично
                  hint="Приёмка не может потребовать DataMatrix — товар уедет в продажу без кода." />
          <Дефект label="Табак без МРЦ" значение={и.табак_без_мрц} критично
                  hint="Продажа выше максимальной цены — нарушение ст. 13 ФЗ-15." />
          <Дефект label="Блюда без ТТК" значение={и.блюда_без_ттк} критично
                  hint="Продажа блюда не списывает сырьё: кофе продан, зерно на остатке." />
          <Дефект label="Устаревшая ставка НДС" значение={и.ставка_устарела}
                  hint="18/118 и 20% в карточках: смена уедет в бухгалтерию с неверным налогом." />
          <Дефект label="Дубли карточек" значение={data.дубли.лишних}
                  hint={`${data.дубли.групп} групп по нормализованному имени. Пока не сведены — обогащать бессмысленно, обогатим не ту.`} />
          <Дефект label="Без класса SKU" значение={и.без_класса}
                  hint="Сопутка, сырьё и блюдо неразличимы — любой отчёт по общепиту врёт." />
          <Дефект label="Предложений обогащения" значение={и.предложений_ждёт}
                  hint="Внешние источники прислали значения; канон подтверждает человек." />
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
