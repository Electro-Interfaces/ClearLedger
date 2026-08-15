/**
 * «За балансом» — раздел «Бухгалтерии» о том, чего в балансе нет.
 *
 * Баланс отвечает, чем компания владеет и кому должна, но часть имущества и
 * обязательств в него не попадает по правилам учёта. Раздел собирает это в двух
 * экранах, и вопросы у них разные:
 *
 * * «Забалансовые счета» — штатный учёт 1С (001–012, МЦ.*): чужое у нас, наше у
 *   других, выданные обеспечения, списанный в убыток долг. Компания либо ведёт его,
 *   либо нет, и «нет» — это тоже ответ, а не пустой экран.
 * * «Не видно в балансе» — то, что в учёте есть всегда, но видно только сопоставлением
 *   двух счетов: самортизированное до нуля имущество, малоценка в эксплуатации,
 *   просроченный долг.
 *
 * Своих цифр экраны не считают — берут посчитанное бэкендом (`/api/books/off-balance*`).
 */
import { useQuery } from '@tanstack/react-query'

import { useFilters } from '@/contexts/FilterContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import {
  getOffBalance, getOffBalanceHidden,
  type OffBalance, type OffBalanceHidden,
} from '@/services/booksService'
import { PerimeterExport } from './perimeterShared'
import { Loading, TableCard, Th } from './OfficePanels'
import { money, num, qty , Td } from './officeShared'

/** Дата снимка сальдо человеческим видом: остаток всегда «на дату», а не «сейчас». */
const asOfNote = (asOf: string | null) =>
  asOf ? `Остаток — на ${asOf}` : 'Снимка сальдо в слое нет: показаны только обороты'

/* ────────────────────────────────────────────────────────────── */
/*                     Забалансовые счета                         */
/* ────────────────────────────────────────────────────────────── */

export function OffBalanceAccounts({ companyId }: { companyId: string }) {
  const { period } = useFilters()
  const q = useQuery({
    queryKey: ['books', 'off-balance', companyId, period.from, period.to],
    queryFn: () => getOffBalance(companyId, { from: period.from, to: period.to }),
    enabled: !!companyId,
  })

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить забалансовый учёт" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d: OffBalance = q.data
  const property = d.groups.filter((g) => g.key !== 'tax_service')
  const service = d.groups.find((g) => g.key === 'tax_service')
  const live = property.filter((g) => g.entries || g.rest || g.restQty)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Счетов в плане" value={num.format(d.planCount)}
          hint="забалансовый контур заведён в 1С" />
        <MetricTile label="Остаток за балансом" value={`${money.format(d.propertyRest)} ₽`}
          hint={asOfNote(d.asOf)} />
        <MetricTile label="Движений за период" value={num.format(d.propertyEntries)}
          hint="приход дебетом, выбытие кредитом" />
        <MetricTile label="Счетов в работе" value={num.format(live.length)}
          hint={`из ${property.length} групп имущества`}
          tone={live.length ? 'success' : undefined} />
      </div>

      {/* Пустой контур — это вывод, а не отсутствие данных, и сказать это надо словами. */}
      {!d.propertyEntries && !d.propertyRest && (
        <Card>
          <CardContent className="p-4 space-y-2 text-sm">
            <div className="font-medium">Забалансовый учёт компания не ведёт</div>
            <p className="text-muted-foreground">
              План счетов содержит {num.format(d.planCount)} забалансовых счетов — контур
              заведён, движений по нему нет ни одного. Само по себе это не нарушение: у
              компании может не быть ни арендованного имущества, ни принятого на
              хранение, ни выданных обеспечений.
            </p>
            <p className="text-muted-foreground">
              Проверить стоит там, где забаланс обязателен: арендованный офис или склад
              учитывается на 001, товар на ответственном хранении — на 002, выданное
              обеспечение — на 009, а списанный в убыток долг пять лет числится на 007 и
              всё это время может быть взыскан. Если такие отношения у компании есть, а
              счета пустые — имущество и обязательства не видны ни в одном отчёте.
            </p>
          </CardContent>
        </Card>
      )}

      <TableCard note="Группы забалансового учёта. Остаток — разница прихода и выбытия: корреспонденции у забалансовой проводки нет"
        head={<>
          <Th>Что учитывается</Th>
          <Th right>Счетов</Th>
          <Th right>Движений</Th>
          <Th right>Приход</Th>
          <Th right>Выбытие</Th>
          <Th right>Остаток</Th>
        </>}>
        {property.map((g) => (
          <tr key={g.key} className="border-b last:border-0">
            <Td>
              <div>{g.label}</div>
              <div className="text-[11px] text-muted-foreground">{g.hint}</div>
            </Td>
            <Td right muted>{num.format(g.accounts)}</Td>
            <Td right muted>{g.entries ? num.format(g.entries) : '—'}</Td>
            <Td right>{g.debit ? `${money.format(g.debit)} ₽` : '—'}</Td>
            <Td right>{g.credit ? `${money.format(g.credit)} ₽` : '—'}</Td>
            <Td right>
              {g.rest ? `${money.format(g.rest)} ₽` : '—'}
              {!!g.restQty && (
                <div className="text-[11px] text-muted-foreground">
                  {qty.format(g.restQty)} ед.
                </div>
              )}
            </Td>
          </tr>
        ))}
      </TableCard>

      {!!d.accounts.length && (
        <TableCard note="Счета, по которым есть движение или остаток"
          head={<>
            <Th>Счёт</Th><Th>Наименование</Th>
            <Th right>Движений</Th><Th right>Приход</Th><Th right>Выбытие</Th><Th right>Остаток</Th>
          </>}>
          {d.accounts.map((a) => (
            <tr key={a.code} className="border-b last:border-0">
              <Td>
                <span className="tabular-nums">{a.code}</span>
                {a.quantitative && (
                  <span className="ml-1.5 text-[11px] text-muted-foreground">кол.</span>
                )}
              </Td>
              <Td>
                <div>{a.name}</div>
                {a.first && (
                  <div className="text-[11px] text-muted-foreground tabular-nums">
                    {a.first === a.last ? a.first : `${a.first} — ${a.last}`}
                  </div>
                )}
              </Td>
              <Td right muted>{a.entries ? num.format(a.entries) : '—'}</Td>
              <Td right>{a.debit ? `${money.format(a.debit)} ₽` : '—'}</Td>
              <Td right>{a.credit ? `${money.format(a.credit)} ₽` : '—'}</Td>
              <Td right>
                {a.rest ? `${money.format(a.rest)} ₽` : '—'}
                {!!a.restQty && (
                  <div className="text-[11px] text-muted-foreground">
                    {qty.format(a.restQty)} ед.
                  </div>
                )}
              </Td>
            </tr>
          ))}
        </TableCard>
      )}

      {!!d.subs.length && (
        <>
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Чьё и по какому основанию
            </div>
            <PerimeterExport companyId={companyId} title="За балансом — аналитика"
            columns={[
              { header: 'Счёт', key: 'account', width: 10 },
              { header: 'Наименование счёта', key: 'name', width: 40 },
              { header: 'Аналитика', key: 'sub1', width: 34 },
              { header: 'Уточнение', key: 'sub2', width: 26 },
              { header: 'Сумма', key: 'amount', width: 16, money: true },
              { header: 'Количество', key: 'qty', width: 12 },
            ]}
            rows={d.subs} />
          </div>
          <TableCard note="Аналитика остатка: без неё «на 002 висит миллион» ничего не значит"
            head={<><Th>Счёт</Th><Th>Аналитика</Th><Th>Уточнение</Th>
              <Th right>Количество</Th><Th right>Сумма</Th></>}>
            {d.subs.map((s, i) => (
              <tr key={`${s.account}-${i}`} className="border-b last:border-0">
                <Td><span className="tabular-nums">{s.account}</span></Td>
                <Td>{s.sub1 ?? '—'}</Td>
                <Td muted>{s.sub2 ?? '—'}</Td>
                <Td right muted>{s.qty ? qty.format(s.qty) : '—'}</Td>
                <Td right>{s.amount ? `${money.format(s.amount)} ₽` : '—'}</Td>
              </tr>
            ))}
          </TableCard>
        </>
      )}

      {!!service && (
        <Card>
          <CardContent className="p-4 text-sm space-y-1">
            <div className="font-medium">Служебные счета налогового учёта</div>
            <p className="text-muted-foreground">
              {service.hint}. Это не имущество компании, поэтому в итог «за балансом» они
              не входят: {num.format(service.accounts)} счетов,{' '}
              {service.entries ? `${num.format(service.entries)} движений` : 'движений нет'}.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                     Не видно в балансе                         */
/* ────────────────────────────────────────────────────────────── */

export function OffBalanceHiddenScreen({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'off-balance-hidden', companyId],
    queryFn: () => getOffBalanceHidden(companyId),
    enabled: !!companyId,
  })

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить разбор" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d: OffBalanceHidden = q.data
  // Самортизированным считается имущество, у которого износ съел стоимость целиком.
  // Порог в рубль, а не ноль: копеечный остаток бывает от округления амортизации.
  const fullyWorn = d.fixedCost > 0 && d.fixedRest < 1

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Основные средства" value={`${money.format(d.fixedCost)} ₽`}
          hint={d.asOf ? `первоначальная стоимость на ${d.asOf}` : 'снимка сальдо нет'} />
        <MetricTile label="Накоплен износ" value={`${money.format(d.fixedWear)} ₽`}
          hint="счёт 02 — сколько стоимости уже в расходах" />
        <MetricTile label="Остаточная стоимость" value={`${money.format(d.fixedRest)} ₽`}
          hint={fullyWorn ? 'ноль: имущество самортизировано полностью' : 'то, что видно в балансе'}
          tone={fullyWorn ? 'warning' : undefined} />
        <MetricTile label="Списано в затраты" value={`${money.format(d.lowValueTotal)} ₽`}
          hint="малоценка и инвентарь: расход признан сразу" />
      </div>

      <Card>
        <CardContent className="p-4 space-y-2 text-sm">
          <div className="font-medium">Что показывает этот экран</div>
          <p className="text-muted-foreground">
            Здесь не забалансовые счета, а имущество и долги, которые в учёте есть, а в
            балансе видны нулём или не тем, чем являются. Три случая: имущество,
            самортизированное до нуля и продолжающее работать; малоценка, списанная в
            затраты в момент покупки; долг, по которому истёк срок исковой давности —
            в активе он стоит, а взыскать его нельзя.
          </p>
        </CardContent>
      </Card>

      {!d.fixedCost ? (
        <Card>
          <CardContent className="p-4 text-sm">
            <div className="font-medium">Основных средств на учёте нет</div>
            <p className="text-muted-foreground mt-1">
              Счета 01 и 02 в остатках пусты. Для торговой компании это обычно означает,
              что помещения и техника арендуются, а покупки не дотягивают до стоимостного
              лимита и списываются в расходы сразу. Проверить стоит другое: если
              оборудование или транспорт у компании фактически есть, они должны быть либо
              на 01, либо — если арендованы — на забалансовом 001.
            </p>
          </CardContent>
        </Card>
      ) : (
        <TableCard note={fullyWorn
          ? 'Износ съел стоимость целиком: в балансе строка нулевая, имущество работает'
          : 'Основные средства по данным сальдо'}
          head={<><Th>Счёт</Th><Th>Объект</Th><Th right>Первоначальная стоимость</Th></>}>
          {d.fixed.map((f, i) => (
            <tr key={`${f.account}-${i}`} className="border-b last:border-0">
              <Td><span className="tabular-nums">{f.account}</span></Td>
              <Td>{f.sub ?? f.name ?? '—'}</Td>
              <Td right>{money.format(f.cost)} ₽</Td>
            </tr>
          ))}
        </TableCard>
      )}

      {!!d.lowValue.length && (
        <TableCard note="Списано в затраты при передаче в эксплуатацию. Именно это и учитывают на счетах МЦ — чтобы вещь не терялась после списания стоимости"
          head={<><Th>Что списано</Th><Th>Куда отнесено</Th>
            <Th right>Операций</Th><Th right>Сумма</Th></>}>
          {d.lowValue.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              <Td><span className="tabular-nums">{r.account_kt}</span></Td>
              <Td muted><span className="tabular-nums">{r.account_dt}</span></Td>
              <Td right muted>{num.format(r.count)}</Td>
              <Td right>{money.format(r.amount)} ₽</Td>
            </tr>
          ))}
        </TableCard>
      )}

      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Долг со сроком давности больше трёх лет
        </div>
        {!!d.stale.length && (
          <PerimeterExport companyId={companyId} title="Просроченный долг"
            columns={[
            { header: 'Покупатель', key: 'counterparty', width: 40 },
            { header: 'Счетов', key: 'count', width: 10 },
            { header: 'Не закрыто', key: 'amount', width: 16, money: true },
            { header: 'Самый старый', key: 'oldest', width: 14 },
            { header: 'Последний', key: 'last', width: 14 },
          ]}
            rows={d.stale} />
        )}
      </div>
      {d.stale.length ? (
        <TableCard note={`Всего ${money.format(d.staleTotal)} ₽. Три года — общий срок исковой давности; после него взыскание через суд невозможно, а долг подлежит списанию на 91 с переносом на забалансовый 007`}
          head={<><Th>Покупатель</Th><Th right>Счетов</Th>
            <Th right>Самый старый</Th><Th right>Не закрыто</Th></>}>
          {d.stale.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              <Td>{r.counterparty}</Td>
              <Td right muted>{num.format(r.count)}</Td>
              <Td right muted><span className="tabular-nums">{r.oldest}</span></Td>
              <Td right>{money.format(r.amount)} ₽</Td>
            </tr>
          ))}
        </TableCard>
      ) : (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Счетов старше трёх лет с непогашенным остатком не нашлось.
          </CardContent>
        </Card>
      )}
      {!!d.staleUnknown && (
        <p className="text-[11px] text-muted-foreground">
          Ещё {num.format(d.staleUnknown)} счетов старше трёх лет регистр не свёл с
          оплатой: по ним неизвестно, погашены они или нет, и в расчёт они не взяты.
          Ноль вместо «неизвестно» дал бы просроченный долг, которого может не быть.
        </p>
      )}
    </div>
  )
}
