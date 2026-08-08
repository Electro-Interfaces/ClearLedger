import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Send } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  getStoreAssortmentRules,
  getStoreStations,
  findNsiItems,
  publishStoreAssortment,
  setStoreAssortmentRule,
} from '@/services/storeService'
import { StoreCommercialPolicyNotice } from './StoreCommercialPolicyNotice'
import { useCentralCommercialWrite } from './useStoreCommercialPolicy'

export function StoreAssortmentPolicyPanel() {
  const client = useQueryClient()
  const centralWrite = useCentralCommercialWrite()
  const [selectedStation, setSelectedStation] = useState<number | null>(null)
  const [itemUuid, setItemUuid] = useState('')
  const [itemSearch, setItemSearch] = useState('')
  const [active, setActive] = useState(false)
  const [reason, setReason] = useState('')
  const [validFrom, setValidFrom] = useState('')
  const [validTo, setValidTo] = useState('')
  const [defaultActive, setDefaultActive] = useState(true)

  const stations = useQuery({
    queryKey: ['store-stations'],
    queryFn: getStoreStations,
    refetchInterval: 60_000,
  })
  const stationId = selectedStation ?? stations.data?.stations[0]?.station_id ?? 208
  const rules = useQuery({
    queryKey: ['store-assortment-rules', stationId],
    queryFn: () => getStoreAssortmentRules(stationId),
    enabled: Boolean(stations.data?.stations.length),
  })
  const station = stations.data?.stations.find((item) => item.station_id === stationId)
  const itemOptions = useQuery({
    queryKey: ['store-assortment-item-search', stationId, itemSearch],
    queryFn: () => findNsiItems(itemSearch.trim(), stationId),
    enabled: itemSearch.trim().length >= 2 && !itemUuid,
  })

  const save = useMutation({
    mutationFn: () => setStoreAssortmentRule(stationId, itemUuid.trim(), {
      active,
      reason: reason.trim() || null,
      valid_from: validFrom ? new Date(validFrom).toISOString() : null,
      valid_to: validTo ? new Date(validTo).toISOString() : null,
    }),
    onSuccess: async () => {
      setItemUuid('')
      setItemSearch('')
      setReason('')
      await client.invalidateQueries({ queryKey: ['store-assortment-rules', stationId] })
      toast.success('Правило ассортимента сохранено')
    },
    onError: (error: Error) => toast.error('Не удалось сохранить правило', { description: error.message }),
  })
  const publish = useMutation({
    mutationFn: () => publishStoreAssortment(stationId, defaultActive),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['store-stations'] })
      toast.success(`Политика АЗС ${stationId} отправлена на проверку`, {
        description: 'Агент сравнит её с кассой без записи в NeftoMS.',
      })
    },
    onError: (error: Error) => toast.error('Не удалось отправить политику', { description: error.message }),
  })

  const check = station?.cash_policy
  const differenceCount = check
    ? check.missing + check.extra + check.price_diff + check.code_diff + check.skipped
    : 0

  return (
    <section className="px-6 pt-6" aria-labelledby="assortment-policy-title">
      <div className="rounded-lg border border-border bg-card/40 p-4 space-y-4">
        <StoreCommercialPolicyNotice />
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h3 id="assortment-policy-title" className="text-sm font-semibold">Политика станции и проверка кассы</h3>
            <p className="mt-1 text-xs text-muted-foreground max-w-3xl">
              Явные стопы и включения едут агенту. Агент собирает ожидаемый ассортимент,
              цены, коды и НДС22 для готовой продукции и сравнивает их с NeftoMS.
              Режим безопасный: запись в кассу выключена.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select value={stationId} onChange={(event) => setSelectedStation(Number(event.target.value))}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs"
              aria-label="Станция для ассортиментной политики">
              {(stations.data?.stations ?? []).map((item) => (
                <option key={item.station_id} value={item.station_id}>АЗС {item.station_id}</option>
              ))}
            </select>
            <Button size="sm" onClick={() => publish.mutate()}
              disabled={!centralWrite || publish.isPending || !stations.data?.stations.length}>
              <Send />{publish.isPending ? 'Отправляем…' : 'Отправить в dry-run'}
            </Button>
          </div>
        </div>

        <div className={`rounded-md border px-3 py-2 text-xs flex items-start gap-2 ${
          check?.ready ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-amber-500/30 bg-amber-500/5'
        }`}>
          {check?.ready ? <CheckCircle2 className="mt-0.5 size-4 text-emerald-400" />
            : <AlertTriangle className="mt-0.5 size-4 text-amber-400" />}
          <div>
            {!check && 'Агент ещё не проверял ассортимент против кассы.'}
            {check?.ready && `Dry-run ${check.policy_id.slice(0, 8)} совпал: кассу можно готовить к отдельному этапу включения.`}
            {check && !check.ready && (
              <>Dry-run {check.policy_id.slice(0, 8)}: {differenceCount} расхождений —
                нет в кассе {check.missing}, лишних {check.extra}, цен {check.price_diff},
                кодов {check.code_diff}, исключено до выгрузки {check.skipped}.</>
            )}
          </div>
        </div>

        <div className="grid gap-2 md:grid-cols-[minmax(220px,1.4fr)_auto_minmax(180px,1fr)_repeat(2,minmax(150px,.8fr))_auto] items-end">
          <label className="relative text-xs text-muted-foreground">Товар
            <input value={itemSearch}
              onChange={(event) => { setItemSearch(event.target.value); setItemUuid('') }}
              placeholder="начните вводить название или штрихкод"
              role="combobox" aria-expanded={Boolean(itemOptions.data?.items.length && !itemUuid)}
              aria-controls="assortment-item-options"
              className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-foreground" />
            {(itemOptions.data?.items.length ?? 0) > 0 && !itemUuid && (
              <div id="assortment-item-options" role="listbox"
                className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-popover p-1 shadow-lg">
                {itemOptions.data?.items.map((item) => (
                  <button key={item.id} type="button" role="option"
                    onClick={() => { setItemUuid(item.external_uuid); setItemSearch(item.name) }}
                    className="block w-full rounded px-2 py-2 text-left hover:bg-muted focus:bg-muted">
                    <span className="block text-xs text-foreground">{item.name}</span>
                    <span className="block text-[10px] text-muted-foreground">
                      {item.unit} · {item.vat_rate} · остаток {item.qty}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </label>
          <label className="h-8 flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />
            разрешён
          </label>
          <label className="text-xs text-muted-foreground">Причина
            <input value={reason} onChange={(event) => setReason(event.target.value)}
              placeholder={active ? 'локальная позиция' : 'стоп-лист'}
              className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-foreground" />
          </label>
          <label className="text-xs text-muted-foreground">С
            <input type="datetime-local" value={validFrom} onChange={(event) => setValidFrom(event.target.value)}
              className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-foreground" />
          </label>
          <label className="text-xs text-muted-foreground">По
            <input type="datetime-local" value={validTo} onChange={(event) => setValidTo(event.target.value)}
              className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-foreground" />
          </label>
          <Button size="sm" variant="outline" onClick={() => save.mutate()}
            disabled={!centralWrite || !itemUuid.trim() || save.isPending}>Сохранить</Button>
        </div>

        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>Явных правил: {rules.data?.rules.length ?? 0}</span>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={defaultActive}
              onChange={(event) => setDefaultActive(event.target.checked)} />
            товары без правила разрешены
          </label>
        </div>
        {(rules.data?.rules.length ?? 0) > 0 && (
          <div className="overflow-x-auto rounded-md border border-border/60">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground"><tr className="border-b border-border/60">
                <th className="px-3 py-2 text-left">Товар</th><th className="px-3 py-2 text-left">Решение</th>
                <th className="px-3 py-2 text-left">Период</th><th className="px-3 py-2 text-left">Причина</th>
              </tr></thead>
              <tbody>{rules.data?.rules.map((rule) => (
                <tr key={rule.item_uuid} className="border-b border-border/40 last:border-0">
                  <td className="px-3 py-2"><div>{rule.name}</div><div className="text-[10px] text-muted-foreground">{rule.item_uuid}</div></td>
                  <td className={`px-3 py-2 ${rule.active ? 'text-emerald-400' : 'text-amber-400'}`}>{rule.active ? 'разрешён' : 'стоп'}</td>
                  <td className="px-3 py-2 text-muted-foreground">{rule.valid_from ? new Date(rule.valid_from).toLocaleString('ru-RU') : 'сейчас'} — {rule.valid_to ? new Date(rule.valid_to).toLocaleString('ru-RU') : 'без срока'}</td>
                  <td className="px-3 py-2 text-muted-foreground">{rule.reason || '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
