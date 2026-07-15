/**
 * Общие панели вспомогательной области «Взаимодействие»: Заявки, Инфо.
 * Используются и в модалке (шапка), и в правом доке (контекст).
 */
import {
  LifeBuoy, Sparkles, Phone, Keyboard, FileText, Database, GitBranch,
} from 'lucide-react'
import { APP_VERSION } from '@/config/version'

export function ContactList() {
  const contacts = [
    { name: 'Михеев Андрей Геннадьевич', role: 'Куратор проекта внедрения', tel: '+7-921-953-06-21' },
  ]
  return (
    <div className="mt-2 w-full max-w-md space-y-2">
      {contacts.map((c) => (
        <a
          key={c.tel}
          href={`tel:${c.tel.replace(/[^+\d]/g, '')}`}
          className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/50 px-3.5 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-accent"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 dark:bg-primary/20">
            <Phone className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground">{c.name}</div>
            <div className="truncate text-xs text-muted-foreground">{c.role}</div>
          </div>
          <span className="shrink-0 font-mono text-sm text-primary">{c.tel}</span>
        </a>
      ))}
    </div>
  )
}

export function TicketsPanel() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 dark:bg-primary/20">
        <LifeBuoy className="h-8 w-8 text-primary" />
      </div>
      <div className="space-y-1.5">
        <h3 className="text-lg font-semibold text-foreground">Заявки в поддержку</h3>
        <p className="max-w-md text-sm text-muted-foreground">
          Учёт заявок появится в следующих версиях. Сейчас вопросы и ошибки фиксируем напрямую
          у куратора проекта — приложите скриншот и шаги воспроизведения.
        </p>
      </div>
      <ContactList />
    </div>
  )
}

export function InfoPanel() {
  const sections = [
    { icon: FileText, title: 'Загрузка и нормализация', text: 'Приём документов с касс/STS, классификация, проверка и сверка перед выгрузкой в 1С.' },
    { icon: Database, title: 'Контур 1С', text: 'Подключение к БП ГИГ, справочники, документы, цены, партии FIFO, периоды и учётная политика.' },
    { icon: GitBranch, title: 'Сверка и закрытие', text: 'Трёхсторонняя сверка (касса · процессинг · банк) и прогноз закрытия месяца.' },
  ]
  const hotkeys = [
    { keys: 'Ctrl + B', text: 'Свернуть / развернуть боковое меню' },
    { keys: 'Ctrl + K', text: 'Открыть «Инфо»' },
  ]
  return (
    <div className="mx-auto max-w-2xl space-y-6 px-5 py-6">
      <div className="flex items-start gap-4">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-700 shadow-lg">
          <Sparkles className="h-7 w-7 text-white" />
        </div>
        <div className="space-y-1">
          <h3 className="text-xl font-semibold text-foreground">TradeLedger</h3>
          <p className="text-sm text-muted-foreground">
            Рабочее место менеджера: приём, классификация, сверка и выгрузка учётных документов
            сети АЗС в 1С:Бухгалтерию ГазИнвестГрупп.
          </p>
          <span className="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-xs font-medium text-muted-foreground">
            версия v{APP_VERSION}
          </span>
        </div>
      </div>

      <div className="space-y-2.5">
        <h4 className="text-sm font-semibold text-foreground">Что внутри</h4>
        {sections.map((s) => (
          <div key={s.title} className="flex items-start gap-3 rounded-xl border border-border/50 bg-secondary/40 p-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 dark:bg-primary/20">
              <s.icon className="h-4 w-4 text-primary" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground">{s.title}</div>
              <div className="text-xs text-muted-foreground">{s.text}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-2.5">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Keyboard className="h-4 w-4 text-muted-foreground" />
          Горячие клавиши
        </h4>
        <div className="rounded-xl border border-border/50 bg-secondary/40">
          {hotkeys.map((h, i) => (
            <div
              key={h.keys}
              className={`flex items-center justify-between px-3.5 py-2.5 ${i > 0 ? 'border-t border-border/50' : ''}`}
            >
              <span className="text-sm text-muted-foreground">{h.text}</span>
              <kbd className="rounded-md border border-border bg-background px-2 py-0.5 font-mono text-xs text-foreground">{h.keys}</kbd>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border/50 bg-secondary/40 p-3.5">
        <h4 className="mb-2 text-sm font-semibold text-foreground">Поддержка проекта</h4>
        <ContactList />
      </div>
    </div>
  )
}
