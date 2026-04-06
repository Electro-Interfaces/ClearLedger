/**
 * Панель нормализации — конвертация первичных документов (Слой 1) в нормализованную базу (Слой 2).
 * Вертикальное меню: Конвейер / Правила / Маппинг / Агенты / Журнал.
 * Рабочая область: зависит от выбранного раздела.
 */

import { useState } from 'react'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  ArrowRight, CheckCircle2, AlertTriangle, XCircle, Clock,
  Play, Bot, FileText, Settings2, ListChecks, History,
  Sparkles, ArrowRightLeft, RefreshCw,
} from 'lucide-react'

type NormTab = 'pipeline' | 'rules' | 'mapping' | 'agents' | 'log'

const NORM_MENU: CentralMenuItem[] = [
  { key: 'pipeline', label: 'Конвейер' },
  { key: 'rules', label: 'Правила' },
  { key: 'mapping', label: 'Маппинг' },
  { key: 'agents', label: 'Агенты' },
  { key: 'log', label: 'Журнал' },
]

/* ── Конвейер ── */

interface PipelineStage {
  key: string
  label: string
  count: number
  icon: React.ComponentType<{ className?: string }>
  color: string
}

const DEMO_STAGES: PipelineStage[] = [
  { key: 'queue', label: 'Очередь', count: 12, icon: Clock, color: 'text-muted-foreground' },
  { key: 'processing', label: 'Обработка', count: 3, icon: RefreshCw, color: 'text-blue-500' },
  { key: 'review', label: 'Проверка', count: 5, icon: AlertTriangle, color: 'text-amber-500' },
  { key: 'accepted', label: 'Принято', count: 847, icon: CheckCircle2, color: 'text-emerald-500' },
  { key: 'rejected', label: 'Отклонено', count: 2, icon: XCircle, color: 'text-red-500' },
]

interface DemoDoc {
  id: string
  name: string
  type: string
  source: string
  date: string
  status: 'queue' | 'processing' | 'review' | 'accepted' | 'rejected'
  issues: number
  version: number
}

const DEMO_DOCS: DemoDoc[] = [
  { id: '1', name: 'Смена №1847', type: 'Сменный отчёт', source: 'STS API', date: '05.04.2026', status: 'review', issues: 2, version: 1 },
  { id: '2', name: 'Смена №1848', type: 'Сменный отчёт', source: 'STS API', date: '05.04.2026', status: 'processing', issues: 0, version: 1 },
  { id: '3', name: 'ТТН №4521', type: 'Поступление', source: 'STS API', date: '05.04.2026', status: 'queue', issues: 0, version: 1 },
  { id: '4', name: 'Смена №1846', type: 'Сменный отчёт', source: 'STS API', date: '04.04.2026', status: 'accepted', issues: 0, version: 2 },
  { id: '5', name: 'ТТН №4520', type: 'Поступление', source: 'STS API', date: '04.04.2026', status: 'accepted', issues: 0, version: 1 },
  { id: '6', name: 'Акт сверки №12', type: 'Сверка', source: 'Файл (Excel)', date: '03.04.2026', status: 'review', issues: 1, version: 1 },
  { id: '7', name: 'Выписка банка', type: 'Банковская', source: 'Файл (CSV)', date: '03.04.2026', status: 'review', issues: 3, version: 1 },
  { id: '8', name: 'Смена №1845', type: 'Сменный отчёт', source: 'STS API', date: '03.04.2026', status: 'rejected', issues: 1, version: 1 },
]

const STATUS_BADGE: Record<DemoDoc['status'], { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  queue: { label: 'В очереди', variant: 'outline' },
  processing: { label: 'Обработка', variant: 'default' },
  review: { label: 'Проверка', variant: 'secondary' },
  accepted: { label: 'Принято', variant: 'outline' },
  rejected: { label: 'Отклонено', variant: 'destructive' },
}

function PipelineView() {
  const [filterStage, setFilterStage] = useState<string | null>(null)
  const filteredDocs = filterStage ? DEMO_DOCS.filter((d) => d.status === filterStage) : DEMO_DOCS

  return (
    <div className="p-4 space-y-4">
      {/* Визуализация конвейера */}
      <div className="flex items-center gap-1">
        {DEMO_STAGES.map((stage, i) => (
          <div key={stage.key} className="flex items-center">
            <button
              onClick={() => setFilterStage(filterStage === stage.key ? null : stage.key)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors ${
                filterStage === stage.key
                  ? 'border-primary bg-primary/5'
                  : 'border-border/50 bg-card hover:border-border'
              }`}
            >
              <stage.icon className={`h-4 w-4 ${stage.color}`} />
              <div className="text-left">
                <p className="text-[10px] text-muted-foreground">{stage.label}</p>
                <p className="text-sm font-bold">{stage.count}</p>
              </div>
            </button>
            {i < DEMO_STAGES.length - 1 && (
              <ArrowRight className="h-3 w-3 text-muted-foreground/30 mx-1 shrink-0" />
            )}
          </div>
        ))}
      </div>

      {/* Управление */}
      <div className="flex items-center gap-2">
        <Button size="sm" className="h-7 text-xs gap-1.5">
          <Play className="h-3 w-3" />
          Запустить обработку
        </Button>
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
          <Bot className="h-3 w-3" />
          Подключить агента
        </Button>
        {filterStage && (
          <button
            onClick={() => setFilterStage(null)}
            className="text-[11px] text-muted-foreground hover:text-foreground ml-auto"
          >
            Показать все
          </button>
        )}
      </div>

      {/* Таблица документов */}
      <Table>
        <TableHeader>
          <TableRow className="text-[10px]">
            <TableHead className="h-7 px-2">Документ</TableHead>
            <TableHead className="h-7">Тип</TableHead>
            <TableHead className="h-7">Источник</TableHead>
            <TableHead className="h-7">Дата</TableHead>
            <TableHead className="h-7 text-center">v</TableHead>
            <TableHead className="h-7 text-center">Проблемы</TableHead>
            <TableHead className="h-7">Статус</TableHead>
            <TableHead className="h-7 text-right">Действия</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filteredDocs.map((doc) => {
            const badge = STATUS_BADGE[doc.status]
            return (
              <TableRow key={doc.id} className="text-[11px]">
                <TableCell className="py-1.5 px-2 font-medium">{doc.name}</TableCell>
                <TableCell className="py-1.5 text-muted-foreground">{doc.type}</TableCell>
                <TableCell className="py-1.5 text-muted-foreground">{doc.source}</TableCell>
                <TableCell className="py-1.5">{doc.date}</TableCell>
                <TableCell className="py-1.5 text-center">
                  {doc.version > 1 ? (
                    <span className="text-primary font-medium">v{doc.version}</span>
                  ) : (
                    <span className="text-muted-foreground">v{doc.version}</span>
                  )}
                </TableCell>
                <TableCell className="py-1.5 text-center">
                  {doc.issues > 0 ? (
                    <span className="text-amber-500 font-medium">{doc.issues}</span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="py-1.5">
                  <Badge variant={badge.variant} className="text-[9px] h-4 px-1.5">{badge.label}</Badge>
                </TableCell>
                <TableCell className="py-1.5 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {doc.status === 'review' && (
                      <>
                        <Button variant="ghost" size="icon" className="h-5 w-5" title="Принять">
                          <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-5 w-5" title="Отклонить">
                          <XCircle className="h-3 w-3 text-red-500" />
                        </Button>
                      </>
                    )}
                    {doc.status === 'queue' && (
                      <Button variant="ghost" size="icon" className="h-5 w-5" title="Обработать">
                        <Play className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

/* ── Правила ── */

interface NormRule {
  id: string
  name: string
  description: string
  docTypes: string[]
  active: boolean
  auto: boolean
}

const DEMO_RULES: NormRule[] = [
  { id: '1', name: 'Маппинг номенклатуры', description: 'Коды POS → единый справочник (АИ-92, АИ-95, ДТ)', docTypes: ['Сменный отчёт', 'ТТН'], active: true, auto: true },
  { id: '2', name: 'Пересчёт единиц', description: 'кг → литры по плотности партии', docTypes: ['ТТН'], active: true, auto: true },
  { id: '3', name: 'Каналы оплаты', description: 'Типы оплаты → виртуальные склады (Яндекс, Карты, Ведомости)', docTypes: ['Сменный отчёт'], active: true, auto: true },
  { id: '4', name: 'Сверка с 1С', description: 'Проверка по закрытым периодам — суммы, остатки, проводки', docTypes: ['Все'], active: true, auto: false },
  { id: '5', name: 'Валидация сумм', description: 'Контроль: сумма = объём × цена, НДС = сумма × 22/122', docTypes: ['Все'], active: true, auto: true },
  { id: '6', name: 'Дедупликация', description: 'Проверка fingerprint — обнаружение дублей и обновлённых версий', docTypes: ['Все'], active: true, auto: true },
]

function RulesView() {
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Правила трансформации входных данных</p>
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
          <Settings2 className="h-3 w-3" />
          Добавить правило
        </Button>
      </div>

      <div className="space-y-2">
        {DEMO_RULES.map((rule) => (
          <Card key={rule.id} className={`${rule.active ? '' : 'opacity-50'}`}>
            <CardContent className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <ListChecks className="h-4 w-4 text-primary shrink-0" />
                    <p className="text-sm font-medium">{rule.name}</p>
                    {rule.auto && <Badge variant="outline" className="text-[9px] h-4 px-1.5">Авто</Badge>}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-1">{rule.description}</p>
                  <div className="flex items-center gap-1 mt-1.5">
                    {rule.docTypes.map((dt) => (
                      <span key={dt} className="text-[9px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{dt}</span>
                    ))}
                  </div>
                </div>
                <div className={`h-2 w-2 rounded-full mt-1.5 ${rule.active ? 'bg-emerald-500' : 'bg-muted-foreground/30'}`} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

/* ── Маппинг ── */

interface MappingEntry {
  source: string
  target: string
  type: string
  confidence: number
}

const DEMO_MAPPINGS: MappingEntry[] = [
  { source: '92-К5', target: 'АИ-92 (л)', type: 'Номенклатура', confidence: 100 },
  { source: '95-К5', target: 'АИ-95 (л)', type: 'Номенклатура', confidence: 100 },
  { source: 'ДТ-Л-К5', target: 'ДТ (л)', type: 'Номенклатура', confidence: 100 },
  { source: 'Наличные', target: 'Касса АЗС', type: 'Канал оплаты', confidence: 100 },
  { source: 'Банковская карта', target: 'Эквайринг', type: 'Канал оплаты', confidence: 100 },
  { source: 'Яндекс.Заправки', target: 'Яндекс (виртуальный)', type: 'Канал оплаты', confidence: 95 },
  { source: 'Ведомость', target: 'Ведомости (виртуальный)', type: 'Канал оплаты', confidence: 100 },
  { source: 'Талон', target: 'Игнорировать', type: 'Канал оплаты', confidence: 90 },
]

function MappingView() {
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Таблицы соответствия: входные данные → внутренний формат</p>
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
          <ArrowRightLeft className="h-3 w-3" />
          Редактировать
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow className="text-[10px]">
            <TableHead className="h-7 px-2">Источник</TableHead>
            <TableHead className="h-7 px-2">
              <ArrowRight className="h-3 w-3 inline" />
            </TableHead>
            <TableHead className="h-7">Целевое значение</TableHead>
            <TableHead className="h-7">Тип</TableHead>
            <TableHead className="h-7 text-right">Точность</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {DEMO_MAPPINGS.map((m, i) => (
            <TableRow key={i} className="text-[11px]">
              <TableCell className="py-1.5 px-2 font-mono text-xs">{m.source}</TableCell>
              <TableCell className="py-1.5 px-2">
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
              </TableCell>
              <TableCell className="py-1.5 font-medium">{m.target}</TableCell>
              <TableCell className="py-1.5 text-muted-foreground">{m.type}</TableCell>
              <TableCell className="py-1.5 text-right">
                <span className={m.confidence === 100 ? 'text-emerald-500' : 'text-amber-500'}>
                  {m.confidence}%
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/* ── Агенты ── */

interface Agent {
  id: string
  name: string
  description: string
  status: 'active' | 'idle' | 'disabled'
  tasks: number
  processed: number
}

const DEMO_AGENTS: Agent[] = [
  { id: '1', name: 'Классификатор документов', description: 'AI-определение типа документа, категории, полей', status: 'idle', tasks: 0, processed: 234 },
  { id: '2', name: 'Валидатор сумм', description: 'Проверка арифметики: объём × цена = сумма, НДС, итоги', status: 'idle', tasks: 0, processed: 891 },
  { id: '3', name: 'Сверщик с 1С', description: 'Сопоставление нормализованных данных с проводками 1С', status: 'disabled', tasks: 0, processed: 0 },
  { id: '4', name: 'Детектор аномалий', description: 'Выявление нетипичных отклонений: объёмы, цены, остатки', status: 'idle', tasks: 0, processed: 156 },
]

const AGENT_STATUS: Record<Agent['status'], { label: string; color: string }> = {
  active: { label: 'Работает', color: 'bg-emerald-500' },
  idle: { label: 'Готов', color: 'bg-blue-500' },
  disabled: { label: 'Отключён', color: 'bg-muted-foreground/30' },
}

function AgentsView() {
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">AI-агенты для глубокого анализа и обработки</p>
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
          <Bot className="h-3 w-3" />
          Настроить
        </Button>
      </div>

      <div className="grid gap-2">
        {DEMO_AGENTS.map((agent) => {
          const st = AGENT_STATUS[agent.status]
          return (
            <Card key={agent.id}>
              <CardContent className="p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Bot className="h-4 w-4 text-primary shrink-0" />
                      <p className="text-sm font-medium">{agent.name}</p>
                      <div className="flex items-center gap-1.5">
                        <div className={`h-1.5 w-1.5 rounded-full ${st.color}`} />
                        <span className="text-[10px] text-muted-foreground">{st.label}</span>
                      </div>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1">{agent.description}</p>
                    <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground">
                      {agent.tasks > 0 && <span>В работе: <strong className="text-foreground">{agent.tasks}</strong></span>}
                      <span>Обработано: <strong className="text-foreground">{agent.processed}</strong></span>
                    </div>
                  </div>
                  {agent.status !== 'disabled' ? (
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" title="Запустить">
                      <Play className="h-3.5 w-3.5" />
                    </Button>
                  ) : (
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 opacity-30" title="Недоступен" disabled>
                      <Play className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

/* ── Журнал ── */

interface LogEntry {
  time: string
  action: string
  doc: string
  result: 'ok' | 'warning' | 'error'
  details: string
}

const DEMO_LOG: LogEntry[] = [
  { time: '14:32', action: 'Нормализация', doc: 'Смена №1846', result: 'ok', details: 'Принято → v2 (обновлённые данные)' },
  { time: '14:31', action: 'Валидация', doc: 'Смена №1847', result: 'warning', details: '2 расхождения в суммах оплат' },
  { time: '14:30', action: 'Маппинг', doc: 'Смена №1848', result: 'ok', details: '3 номенклатуры, 4 канала оплаты' },
  { time: '14:28', action: 'Загрузка', doc: 'ТТН №4521', result: 'ok', details: 'Из STS API, fingerprint: a7f3...' },
  { time: '14:25', action: 'Агент: Валидатор', doc: 'Выписка банка', result: 'error', details: '3 расхождения с данными АЗС' },
  { time: '14:20', action: 'Дедупликация', doc: 'Смена №1846', result: 'warning', details: 'Обнаружена новая версия, замена v1→v2' },
  { time: '13:55', action: 'Нормализация', doc: 'Акт сверки №12', result: 'warning', details: 'Требуется ручная проверка контрагента' },
]

const LOG_ICON: Record<LogEntry['result'], { icon: React.ComponentType<{ className?: string }>; color: string }> = {
  ok: { icon: CheckCircle2, color: 'text-emerald-500' },
  warning: { icon: AlertTriangle, color: 'text-amber-500' },
  error: { icon: XCircle, color: 'text-red-500' },
}

function LogView() {
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">История обработки документов</p>
        <Button size="sm" variant="ghost" className="h-7 text-xs gap-1.5">
          <History className="h-3 w-3" />
          Полный журнал
        </Button>
      </div>

      <div className="space-y-1">
        {DEMO_LOG.map((entry, i) => {
          const { icon: Icon, color } = LOG_ICON[entry.result]
          return (
            <div key={i} className="flex items-start gap-2 py-1.5 border-b border-border/30 last:border-0">
              <span className="text-[10px] text-muted-foreground w-10 shrink-0 pt-0.5">{entry.time}</span>
              <Icon className={`h-3.5 w-3.5 ${color} shrink-0 mt-0.5`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium">{entry.action}</span>
                  <span className="text-[11px] text-muted-foreground">→</span>
                  <span className="text-[11px]">{entry.doc}</span>
                </div>
                <p className="text-[10px] text-muted-foreground">{entry.details}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── Главный компонент ── */

export function NormalizationPanel() {
  const [tab, setTab] = useState<NormTab>('pipeline')

  return (
    <CentralPanelLayout items={NORM_MENU} activeKey={tab} onSelect={(k) => setTab(k as NormTab)}>
      <ScrollArea className="h-full">
        {tab === 'pipeline' && <PipelineView />}
        {tab === 'rules' && <RulesView />}
        {tab === 'mapping' && <MappingView />}
        {tab === 'agents' && <AgentsView />}
        {tab === 'log' && <LogView />}
      </ScrollArea>
    </CentralPanelLayout>
  )
}
