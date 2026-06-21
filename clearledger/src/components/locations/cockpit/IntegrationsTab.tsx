/**
 * Интеграции станции — к каким источникам/каналам она подключена.
 * Источник: location.sourceBindings (STS/MSTO/TradeCorp/1С) + HubEx-связка из metadata.
 * Имена/статусы источников резолвятся через getSources (если источник заведён в компании).
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Plug, Link2, Radio } from 'lucide-react'
import { getSources } from '@/services/sourceService'
import type { ServiceLocation, LocationSourceBinding } from '@/types/location'
import { SectionCard, InfoRow, Placeholder, ScrollTab } from './shared'

const SOURCE_TYPE_LABEL: Record<string, string> = {
  rest: 'STS / REST', '1c': '1С', msto: 'MSTO', tradecorp: 'TradeCorp', ftp: 'FTP', email: 'Email',
}
const STATUS_META: Record<string, { label: string; cls: string }> = {
  connected: { label: 'подключён', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  disconnected: { label: 'отключён', cls: 'bg-muted text-muted-foreground' },
  error: { label: 'ошибка', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  draft: { label: 'черновик', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
}
const LINK_STATUS_META: Record<string, { label: string; cls: string }> = {
  ok: { label: 'связка ok', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  review: { label: 'на проверке', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  conflict: { label: 'конфликт', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  test: { label: 'тест', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  no_match: { label: 'нет связки', cls: 'bg-muted text-muted-foreground' },
}

/** Краткая выжимка параметров привязки (станция/система/сервис-поинт). */
function bindingParams(b: LocationSourceBinding): { label: string; value: string }[] {
  const cfg = b.config ?? {}
  const rows: { label: string; value: string }[] = []
  const pick = (label: string, keys: string[]) => {
    for (const k of keys) {
      if (cfg[k] != null && String(cfg[k]).trim() !== '') { rows.push({ label, value: String(cfg[k]) }); return }
    }
  }
  pick('Система (system_id)', ['system_id', 'systemId', 'systemCode'])
  pick('Станция', ['station', 'station_id', 'stationId', 'stationNumber'])
  pick('MSTO servicePoint', ['servicePointId', 'mstoServicePointId', 'msto_service_point_id'])
  return rows
}

export function IntegrationsTab({ location }: { location: ServiceLocation }) {
  const sources = getSources()
  const bindings = location.sourceBindings ?? []
  const meta = (location.metadata ?? {}) as Record<string, unknown>
  const hubexAssetId = meta.hubexAssetId
  const linkStatus = meta.linkStatus != null ? String(meta.linkStatus) : null

  const hasAny = bindings.length > 0 || hubexAssetId != null

  if (!hasAny) {
    return (
      <ScrollTab>
        <Placeholder
          icon={Plug}
          title="Нет привязок к источникам"
          text="Станция не сопоставлена ни с одним источником данных (STS, MSTO, TradeCorp, 1С). Привязка задаётся при импорте реестра или вручную."
        />
      </ScrollTab>
    )
  }

  return (
    <ScrollTab>
      {bindings.map((b, i) => {
        const src = sources.find((s) => s.id === b.sourceId)
        const typeLabel = src ? (SOURCE_TYPE_LABEL[src.type] ?? src.type) : null
        const status = src ? STATUS_META[src.status] : null
        return (
          <Card key={i}>
            <CardContent className="pt-5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Link2 className="h-4 w-4 text-muted-foreground" />
                <span className="font-medium">{src?.name ?? b.label ?? `Источник ${b.sourceId.slice(0, 8)}`}</span>
                {typeLabel && <Badge variant="outline" className="text-[10px]">{typeLabel}</Badge>}
                {status && <Badge variant="secondary" className={`text-[10px] ${status.cls}`}>{status.label}</Badge>}
              </div>
              {bindingParams(b).length > 0
                ? bindingParams(b).map((r) => <InfoRow key={r.label} label={r.label} value={<span className="font-mono">{r.value}</span>} />)
                : <p className="text-sm text-muted-foreground">{b.label ?? 'Параметры привязки не заданы.'}</p>}
            </CardContent>
          </Card>
        )
      })}

      {hubexAssetId != null && (
        <SectionCard
          title="HubEx (сервис ЭЗС)" icon={Radio}
          action={linkStatus ? <Badge variant="secondary" className={`text-[10px] ${LINK_STATUS_META[linkStatus]?.cls ?? ''}`}>{LINK_STATUS_META[linkStatus]?.label ?? linkStatus}</Badge> : undefined}
        >
          <InfoRow label="HubEx asset_id" value={<span className="font-mono">{String(hubexAssetId)}</span>} />
          {meta.hubexName != null && <InfoRow label="HubEx название" value={String(meta.hubexName)} />}
        </SectionCard>
      )}
    </ScrollTab>
  )
}
