/**
 * Снабжение и расчёты станции.
 * АЗС: приёмы ТТН по станции (STS, реально). Расчёты с поставщиками —
 * каркас-задел (дебиторка/кредиторка пока считается по компании, не по станции).
 */
import { Truck, Banknote, Box, Zap, Fuel } from 'lucide-react'
import { locationStationNumber } from '@/components/reconciliation/locationMapping'
import { useAllReceipts } from '@/hooks/useFuel'
import type { ServiceLocation } from '@/types/location'
import { SectionCard, InfoRow, Placeholder, WipBadge, ScrollTab, typeFlags } from './shared'

export function SupplyTab({ location }: { location: ServiceLocation }) {
  const flags = typeFlags(location.type)

  if (flags.isEv) {
    return (
      <ScrollTab>
        <Placeholder icon={Zap} title="Энергоснабжение"
          text="Учёт поставки электроэнергии для ЭЗС — будущая фаза EV-пайплайна." />
      </ScrollTab>
    )
  }

  if (!flags.isFuel) {
    if (flags.isRetail || flags.isFood) {
      return (
        <ScrollTab>
          <SectionCard title="Поставки товара" icon={Truck} muted action={<WipBadge />}>
            <InfoRow label="Накладных" value="—" />
            <InfoRow label="Сумма закупа" value="—" />
          </SectionCard>
          <p className="text-xs text-muted-foreground/70">
            Поставки сопутки/общепита по станции появятся после привязки накладных к точке.
          </p>
        </ScrollTab>
      )
    }
    return (
      <ScrollTab>
        <Placeholder icon={Box} title="Снабжение не ведётся"
          text="Для офисов снабжение не учитывается." />
      </ScrollTab>
    )
  }

  return <FuelSupply location={location} />
}

/** Снабжение АЗС: приёмы ТТН (STS) + расчёты с поставщиками (задел). */
function FuelSupply({ location }: { location: ServiceLocation }) {
  const stationId = locationStationNumber(location)
  const receiptsQ = useAllReceipts(stationId ?? undefined)
  const receipts = receiptsQ.data ?? []

  if (stationId == null) {
    return (
      <ScrollTab>
        <Placeholder icon={Fuel} title="Станция не сопоставлена с STS"
          text="Укажите номер станции в привязке источника (вкладка «Интеграции») — тогда появятся приёмы ТТН." />
      </ScrollTab>
    )
  }

  return (
    <ScrollTab>
      <SectionCard
        title="Приёмы топлива (ТТН)" icon={Truck}
        action={receipts.length > 0 ? <span className="text-xs text-muted-foreground">всего: {receipts.length}</span> : undefined}
      >
        {receiptsQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка приёмов…</p>}
        {!receiptsQ.isLoading && receipts.length === 0 && (
          <p className="text-sm text-muted-foreground">Приёмов по станции нет (нет закрытых смен с ТТН).</p>
        )}
        {receipts.length > 0 && (
          <div className="space-y-1.5">
            {receipts.slice(0, 50).map((r, i) => (
              <div key={`${r.ttn}-${i}`} className="flex flex-wrap items-center gap-2 border-b border-border/30 py-1.5 text-sm last:border-0">
                <span className="font-mono text-xs text-muted-foreground">ТТН {r.ttn || '—'}</span>
                <span className="font-medium">{r.fuel}</span>
                <span className="text-xs text-muted-foreground">см.{r.shift}</span>
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                  док {Math.round(r.docVolume).toLocaleString('ru-RU')} / факт {Math.round(r.factVolume).toLocaleString('ru-RU')} л
                </span>
              </div>
            ))}
            {receipts.length > 50 && (
              <p className="pt-1 text-xs text-muted-foreground">…показаны первые 50 из {receipts.length}</p>
            )}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Расчёты с поставщиками" icon={Banknote} muted action={<WipBadge>по компании</WipBadge>}>
        <InfoRow label="Кредиторка (60.01)" value="—" />
        <InfoRow label="Дебиторка авансов (60.02)" value="—" />
      </SectionCard>
      <p className="text-xs text-muted-foreground/70">
        Дебиторка/кредиторка в разрезе станции — в разработке: сейчас расчёты ведутся по контрагенту
        в целом (раздел «Аналитика → Дебиторка/кредиторка»), документы 1С привязаны к складу, не к станции.
      </p>
    </ScrollTab>
  )
}
