/**
 * Статус и диагностика станции.
 * Верх — РЕАЛЬНЫЙ операционный статус (смена + журнал истории).
 * Низ — каркас-задел «Диагностика связи» (источник — система PayTerm/fuel-ops,
 * в TradeLedger пока не интегрирована).
 */
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Radio, Server, Cpu, PlugZap } from 'lucide-react'
import { toast } from 'sonner'
import { setOperationalStatus, getOperationalStatusHistory } from '@/services/locationService'
import type { ServiceLocation } from '@/types/location'
import { useCompany } from '@/contexts/CompanyContext'
import { OP_META, OP_OPTIONS, SectionCard, InfoRow, WipBadge, ScrollTab, typeFlags } from './shared'

export function StatusDiagnosticsTab({
  location,
  onChanged,
}: {
  location: ServiceLocation
  onChanged?: () => void
}) {
  const qc = useQueryClient()
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const isFuel = typeFlags(location.type).isFuel
  const curOp = location.operationalStatus ?? 'unknown'

  const historyQ = useQuery({
    queryKey: ['op-status-history', location.id],
    queryFn: () => getOperationalStatusHistory(location.id),
  })

  const [opStatus, setOpStatus] = useState(curOp)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setOpStatus(location.operationalStatus ?? 'unknown')
    setReason('')
  }, [location.id, location.operationalStatus])

  async function applyStatus() {
    if (opStatus === curOp && !reason.trim()) {
      toast.info('Статус не изменён')
      return
    }
    setSaving(true)
    try {
      await setOperationalStatus(location.id, opStatus, reason.trim() || undefined)
      toast.success('Операционный статус обновлён')
      setReason('')
      await qc.invalidateQueries({ queryKey: ['op-status-history', location.id] })
      onChanged?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сменить статус')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ScrollTab maxWidth="max-w-2xl">
      <Card>
        <CardContent className="space-y-3 pt-5">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Текущий статус:</span>
            <Badge variant="secondary" className={OP_META[curOp]?.cls}>{OP_META[curOp]?.label ?? curOp}</Badge>
          </div>
          <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[200px_1fr]">
            <div className="space-y-1.5">
              <Label>Новый статус</Label>
              <Select value={opStatus} onValueChange={setOpStatus}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {OP_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s}>{OP_META[s]?.label ?? s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Причина / комментарий</Label>
              <Input value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="напр. плановое ТО, замена коннектора…" />
            </div>
          </div>
          <Button onClick={applyStatus} disabled={saving} size="sm">
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Применить
          </Button>
        </CardContent>
      </Card>

      <div>
        <div className="mb-2 text-xs font-medium text-muted-foreground">История изменений</div>
        {historyQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
        {historyQ.data && historyQ.data.length === 0 && (
          <p className="text-sm text-muted-foreground">Изменений ещё не было.</p>
        )}
        <div className="space-y-1.5">
          {historyQ.data?.map((h, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 border-b border-border/30 py-1.5 text-sm">
              <span className="text-xs tabular-nums text-muted-foreground">
                {h.at ? new Date(h.at).toLocaleString('ru-RU') : ''}
              </span>
              <Badge variant="outline" className="text-[10px]">{OP_META[h.from ?? '']?.label ?? h.from}</Badge>
              →
              <Badge variant="secondary" className={`text-[10px] ${OP_META[h.to ?? '']?.cls ?? ''}`}>{OP_META[h.to ?? '']?.label ?? h.to}</Badge>
              {h.reason && <span className="text-muted-foreground">· {h.reason}</span>}
              <span className="ml-auto text-xs text-muted-foreground">{h.user}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Диагностика связи ──
          АЗС (топливный профиль): каркас-задел из PayTerm/Gast.
          ЭЗС / прочие типы: нейтральный задел телеметрии (OCPP). */}
      {isFuel && !isEnergy ? (
        <>
          <SectionCard
            title="Канал связи" icon={Radio} muted
            action={<WipBadge>из PayTerm</WipBadge>}
          >
            <InfoRow label="Тип канала" value="LTE / Ethernet" />
            <InfoRow label="Оператор / IP" value="—" />
            <InfoRow label="Последний онлайн" value="—" />
            <InfoRow label="Ping / задержка" value="—" />
          </SectionCard>

          <SectionCard title="Профиль ноды" icon={Server} muted action={<WipBadge>из PayTerm</WipBadge>}>
            <InfoRow label="Профиль" value="economy / minimal" />
            <InfoRow label="hub_url" value="—" />
            <InfoRow label="Ложный offline" value="—" />
          </SectionCard>

          <SectionCard title="Нода / процессы" icon={Cpu} muted action={<WipBadge>из PayTerm</WipBadge>}>
            <InfoRow label="Имя ноды" value="—" />
            <InfoRow label="Версия ПО" value="—" />
            <InfoRow label="network_scan" value="—" />
          </SectionCard>

          <p className="text-xs text-muted-foreground/70">
            Диагностика связи и процессов станции ведётся в системе PayTerm/Gast (skill fuel-ops).
            Интеграция с TradeLedger — в разработке.
          </p>
        </>
      ) : (
        <>
          <SectionCard title="Канал связи" icon={Radio} muted action={<WipBadge>из телеметрии</WipBadge>}>
            <InfoRow label="Тип канала" value="—" />
            <InfoRow label="Последний онлайн" value="—" />
            <InfoRow label="Задержка" value="—" />
          </SectionCard>

          <SectionCard title="Связь со станцией (OCPP)" icon={PlugZap} muted action={<WipBadge>из телеметрии</WipBadge>}>
            <InfoRow label="Версия OCPP" value="—" />
            <InfoRow label="Статус подключения" value="—" />
            <InfoRow label="Последний heartbeat" value="—" />
          </SectionCard>

          <p className="text-xs text-muted-foreground/70">
            Диагностика связи и телеметрия станции (OCPP / показания) будут подтягиваться
            из систем мониторинга. Интеграция с TradeLedger — в разработке.
          </p>
        </>
      )}
    </ScrollTab>
  )
}
