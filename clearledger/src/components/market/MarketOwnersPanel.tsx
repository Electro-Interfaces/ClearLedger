/**
 * Разбор двух ошибок, из-за которых расклад сил врёт (замечание РусГидро 14.09.2026).
 *
 * ПЕРВАЯ — точка под чужим именем. Публичная выгрузка знает одно имя на станцию и
 * ставит его оператором, не различая, владелец это, эксплуатант или поставщик
 * ИТ-системы. Станции EvCar27 в Хабаровске приходят под именем платформы ItCharge,
 * и самого EvCar27 в реестре компаний нет — говорить об интеграции не с кем.
 * Имя владельца при этом почти всегда лежит в названии точки, и разбор его
 * показывает: «этот бренд стоит в названиях 20 точек платформы — это сеть?»
 *
 * ВТОРАЯ — одна станция, посчитанная дважды. Две выгрузки дают одну ЭЗС под разными
 * именами и разными операторами; она завышает и размер рынка, и долю обеих компаний.
 *
 * Обе решает человек, а не алгоритм: повторяющееся слово бывает названием торгового
 * центра, а две точки в пяти метрах — двумя разными станциями у одного входа.
 * Экран отвечает за то, чтобы спорные случаи не пришлось искать глазами.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Copy, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import {
  applyOwnerCandidate, getMarketDuplicates, getOwnerCandidates, resolveDuplicate,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')

function Skeleton({ text }: { text: string }) {
  return (
    <div className="space-y-2" aria-busy="true">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />{text}
      </div>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg border border-border bg-muted/40" />
      ))}
    </div>
  )
}

/** Бренды из названий точек, которые похожи на владельцев сетей. */
export function MarketOwnersPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [взяты, setВзяты] = useState<string[]>([])

  const q = useQuery({
    queryKey: ['market-owner-candidates', companyId],
    queryFn: () => getOwnerCandidates(companyId),
    enabled: !!companyId,
  })
  const привязать = useMutation({
    mutationFn: ({ brand, siteIds }: { brand: string; siteIds: string[] }) =>
      applyOwnerCandidate(companyId, brand, siteIds),
    onSuccess: (_d, v) => {
      setВзяты((prev) => [...prev, v.brand])
      qc.invalidateQueries({ queryKey: ['market-landscape', companyId] })
      qc.invalidateQueries({ queryKey: ['market-operators', companyId] })
      qc.invalidateQueries({ queryKey: ['market-owner-candidates', companyId] })
    },
  })

  if (q.isLoading) return <Skeleton text="Ищем имена владельцев в названиях точек." />

  const кандидаты = (q.data?.candidates ?? []).filter((к) => !взяты.includes(к.brand))

  return (
    <div className="space-y-2">
      <Card><CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
        <span className="flex items-center gap-2 text-sm font-medium">
          <Building2 className="size-4 text-primary" aria-hidden />
          {кандидаты.length === 0
            ? 'Имён владельцев в названиях точек не нашлось.'
            : `Похоже на сети под чужой платформой: ${кандидаты.length} брендов.`}
        </span>
        <span className="text-xs text-muted-foreground">
          на платформах {nf.format(q.data?.sitesOnPlatforms ?? 0)} точек с неподтверждённым
          владельцем
        </span>
      </CardContent></Card>

      {кандидаты.length > 0 && (
        <table hidden {...exportRows('Владелец под вопросом', [
          'Бренд', 'Точек', 'Городов', 'Города', 'Платформа', 'Компания уже заведена',
        ], кандидаты.map((к) => [
          к.brand, к.sites, к.citiesTotal, к.cities.join(', '), к.operatorName,
          к.existing ? 'да' : 'нет',
        ]))} />
      )}

      {кандидаты.map((к) => (
        <Card key={`${к.operatorId}-${к.key}`}>
          <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
            <span className="text-sm font-medium">{к.brand}</span>
            <span className="text-xs text-muted-foreground">
              {nf.format(к.sites)} точек · {к.cities.join(', ')}
              {к.citiesTotal > к.cities.length && ` и ещё ${к.citiesTotal - к.cities.length}`}
            </span>
            <span className="text-xs text-muted-foreground">
              на платформе {к.operatorName}
            </span>
            {к.existing && (
              <span className="text-xs text-success">компания уже заведена</span>
            )}
            <Button size="sm" variant="outline" className="ml-auto"
              disabled={привязать.isPending}
              onClick={() => привязать.mutate({ brand: к.brand, siteIds: к.siteIds })}>
              {привязать.isPending && привязать.variables?.brand === к.brand && (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              )}
              {к.existing ? 'Привязать точки' : 'Это владелец — завести'}
            </Button>
          </CardContent>
        </Card>
      ))}

      <p className="text-xs text-muted-foreground">{q.data?.note}. Эксплуатант у точек
        остаётся прежним: платформа их и правда обслуживает. Меняется ответ на вопрос,
        чей это актив.</p>
    </div>
  )
}

/** Пары точек, которые могут оказаться одной станцией. */
export function MarketDuplicatesPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [радиус, setРадиус] = useState('150')
  const [решены, setРешены] = useState<string[]>([])

  const q = useQuery({
    queryKey: ['market-duplicates', companyId, радиус],
    queryFn: () => getMarketDuplicates(companyId, Number(радиус)),
    enabled: !!companyId,
  })
  const решить = useMutation({
    mutationFn: ({ keepId, dropId, same }: { keepId: string; dropId: string; same: boolean }) =>
      resolveDuplicate(companyId, keepId, dropId, same),
    onSuccess: (_d, v) => {
      setРешены((prev) => [...prev, `${v.keepId}|${v.dropId}`, `${v.dropId}|${v.keepId}`])
      qc.invalidateQueries({ queryKey: ['market-landscape', companyId] })
      qc.invalidateQueries({ queryKey: ['market-sites-list', companyId] })
    },
  })

  if (q.isLoading) return <Skeleton text="Ищем точки, стоящие в одном месте." />

  const пары = (q.data?.pairs ?? []).filter(
    (п) => !решены.includes(`${п.a.id}|${п.b.id}`))

  return (
    <div className="space-y-2">
      <Card><CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
        <span className="flex items-center gap-2 text-sm font-medium">
          <Copy className="size-4 text-primary" aria-hidden />
          {пары.length === 0
            ? 'Точек разных компаний в одном месте не нашлось.'
            : `${nf.format(пары.length)} пар точек разных компаний стоят рядом.`}
        </span>
        <Select value={радиус} onValueChange={setРадиус}>
          <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="50">ближе 50 м</SelectItem>
            <SelectItem value="150">ближе 150 м</SelectItem>
            <SelectItem value="300">ближе 300 м</SelectItem>
          </SelectContent>
        </Select>
        {(q.data?.merged ?? 0) > 0 && (
          <span className="text-xs text-muted-foreground">
            уже склеено {nf.format(q.data!.merged)}
          </span>
        )}
      </CardContent></Card>

      {пары.length > 0 && (
        <table hidden {...exportRows('Спорные точки', [
          'Город', 'Расстояние, м', 'Точка 1', 'Компания 1', 'Портов 1', 'Источник 1',
          'Точка 2', 'Компания 2', 'Портов 2', 'Источник 2',
        ], пары.map((п) => [
          п.city, п.distanceM, п.a.name, п.a.operator, п.a.ports, п.a.source,
          п.b.name, п.b.operator, п.b.ports, п.b.source,
        ]))} />
      )}

      <div className="space-y-2">
        {пары.slice(0, 60).map((п) => (
          <Card key={`${п.a.id}-${п.b.id}`}>
            <CardContent className="space-y-2 p-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="text-sm font-medium text-foreground">{п.city ?? 'город не указан'}</span>
                <span>расстояние {п.distanceM} м</span>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {[п.a, п.b].map((с, i) => (
                  <div key={с.id} className="rounded-md border border-border/60 p-2 text-xs">
                    <div className="font-medium">{с.name}{с.isOurs && ' · наша'}</div>
                    <div className="text-muted-foreground">
                      {с.operator ?? 'компания не указана'}
                      {с.ports != null && ` · портов ${с.ports}`} · источник {с.source}
                    </div>
                    {с.address && <div className="text-muted-foreground">{с.address}</div>}
                    <Button size="xs" variant="outline" className="mt-1.5"
                      disabled={решить.isPending}
                      onClick={() => решить.mutate({
                        keepId: с.id, dropId: i === 0 ? п.b.id : п.a.id, same: true,
                      })}>
                      Это одна станция — оставить эту
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {пары.length > 60 && (
        <p className="text-xs text-muted-foreground">
          Показаны первые 60 пар из {nf.format(пары.length)}; остальные — в выгрузке.
        </p>
      )}
      <p className="text-xs text-muted-foreground">{q.data?.note}. Склейка не удаляет
        запись: у неё своя история наблюдений, и завтра её источник может оказаться
        точнее. Запись остаётся, но из счёта уходит.</p>
    </div>
  )
}
