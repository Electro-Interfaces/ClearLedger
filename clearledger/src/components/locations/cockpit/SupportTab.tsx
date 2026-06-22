/**
 * Поддержка станции — три линии (L1/L2/L3) с эскалацией.
 * Каркас-задел: модели тикетов пока нет, контакты реальны, кнопка «Открыть заявку»
 * мостит к существующему модулю «Взаимодействие» (SupportContext).
 */
import { Button } from '@/components/ui/button'
import { Headset, Wrench, Code2, Phone, ChevronRight, LifeBuoy } from 'lucide-react'
import { useSupportContext } from '@/contexts/SupportContext'
import type { ServiceLocation } from '@/types/location'
import { SectionCard, InfoRow, WipBadge, ScrollTab } from './shared'

const CONTACTS = [
  { name: 'Михеев Андрей Геннадьевич', role: 'Куратор проекта внедрения', tel: '+7-921-953-06-21' },
]

function ContactRow({ name, role, tel }: { name: string; role: string; tel: string }) {
  return (
    <a
      href={`tel:${tel.replace(/[^+\d]/g, '')}`}
      className="flex items-center gap-3 rounded-lg border border-border/60 bg-secondary/40 px-3 py-2 text-left transition-colors hover:border-primary/40 hover:bg-accent"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 dark:bg-primary/20">
        <Phone className="h-3.5 w-3.5 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{name}</div>
        <div className="truncate text-xs text-muted-foreground">{role}</div>
      </div>
      <span className="shrink-0 font-mono text-xs text-primary">{tel}</span>
    </a>
  )
}

export function SupportTab({ location: _location }: { location: ServiceLocation }) {
  const { toggleInteraction } = useSupportContext()

  return (
    <ScrollTab>
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Линии поддержки станции</div>
        <Button size="sm" variant="outline" onClick={() => toggleInteraction('tickets')}>
          <LifeBuoy className="mr-2 h-4 w-4" /> Открыть заявку
        </Button>
      </div>

      {/* Схема эскалации */}
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span className="rounded bg-emerald-500/15 px-2 py-1 text-emerald-600 dark:text-emerald-400">L1 Приём</span>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="rounded bg-amber-500/15 px-2 py-1 text-amber-600 dark:text-amber-400">L2 Техническая</span>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="rounded bg-blue-500/15 px-2 py-1 text-blue-600 dark:text-blue-400">L3 Разработка / вендор</span>
      </div>

      <SectionCard title="L1 — Первая линия" icon={Headset} action={<WipBadge>SLA — задел</WipBadge>}>
        <InfoRow label="Назначение" value="Приём обращений, типовые вопросы" />
        <InfoRow label="SLA реакции" value="—" />
        <div className="mt-3 space-y-2">
          {CONTACTS.map((c) => <ContactRow key={c.tel} {...c} />)}
        </div>
      </SectionCard>

      <SectionCard title="L2 — Вторая линия" icon={Wrench} muted action={<WipBadge />}>
        <InfoRow label="Назначение" value="Технические специалисты, выезды, эскалация" />
        <InfoRow label="Канал" value="HubEx FSM (вкладка «Сервис»)" />
        <InfoRow label="SLA решения" value="—" />
      </SectionCard>

      <SectionCard title="L3 — Разработка / вендор" icon={Code2} muted action={<WipBadge />}>
        <InfoRow label="Назначение" value="Инциденты ПО: PayTerm / 1С / процессинг" />
        <InfoRow label="Эскалация" value="—" />
      </SectionCard>

      <p className="text-xs text-muted-foreground/70">
        Полноценный учёт заявок с уровнями и SLA — будущий модуль. Сейчас обращения фиксируются
        через куратора проекта и сервисные заявки HubEx.
      </p>
    </ScrollTab>
  )
}
