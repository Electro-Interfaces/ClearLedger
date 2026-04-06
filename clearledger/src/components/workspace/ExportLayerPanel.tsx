/**
 * Панель выгрузки (Слой 3) — документы, подготовленные для загрузки в 1С.
 * Документы созданы на основе первичных, прошли нормализацию, сверку, корректировку.
 * Вертикальное меню: Документы / Предпросмотр / Валидация / Загрузка / Анализ.
 */

import { useState } from 'react'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  FileOutput, FileCheck, Eye, Upload, Search,
  CheckCircle2, AlertTriangle, XCircle, Clock,
  ArrowRight, FileText, Loader2, Shield,
  GitBranch, RotateCcw, BarChart3, ListChecks,
} from 'lucide-react'

type ExportTab = 'documents' | 'preview' | 'validation' | 'upload' | 'analysis'

const EXPORT_MENU: CentralMenuItem[] = [
  { key: 'documents', label: 'Документы' },
  { key: 'preview', label: 'Предпросмотр' },
  { key: 'validation', label: 'Валидация' },
  { key: 'upload', label: 'Загрузка' },
  { key: 'analysis', label: 'Анализ' },
]

/* ── Документы ── */

interface ExportDoc {
  id: string
  name: string
  type: string
  sourceDoc: string
  sourceVersion: number
  corrected: boolean
  period: string
  status: 'draft' | 'validated' | 'uploaded' | 'error'
  amount: string
}

const DEMO_EXPORT_DOCS: ExportDoc[] = [
  { id: '1', name: 'Розн. продажи №1847', type: 'Отчёт о розничных продажах', sourceDoc: 'Смена №1847', sourceVersion: 2, corrected: true, period: '04.2026', status: 'draft', amount: '287 450.00' },
  { id: '2', name: 'Поступление ТТН №4520', type: 'Поступление товаров', sourceDoc: 'ТТН №4520', sourceVersion: 1, corrected: false, period: '04.2026', status: 'validated', amount: '1 245 000.00' },
  { id: '3', name: 'Комплектация №4520', type: 'Комплектация номенклатуры', sourceDoc: 'ТТН №4520', sourceVersion: 1, corrected: false, period: '04.2026', status: 'validated', amount: '1 245 000.00' },
  { id: '4', name: 'Перемещение Яндекс №1846', type: 'Перемещение товаров', sourceDoc: 'Смена №1846', sourceVersion: 2, corrected: true, period: '04.2026', status: 'uploaded', amount: '18 320.00' },
  { id: '5', name: 'Розн. продажи №1846', type: 'Отчёт о розничных продажах', sourceDoc: 'Смена №1846', sourceVersion: 2, corrected: false, period: '04.2026', status: 'uploaded', amount: '312 780.50' },
  { id: '6', name: 'Розн. продажи №1845', type: 'Отчёт о розничных продажах', sourceDoc: 'Смена №1845', sourceVersion: 1, corrected: false, period: '04.2026', status: 'error', amount: '198 100.00' },
]

const DOC_STATUS: Record<ExportDoc['status'], { label: string; color: string }> = {
  draft: { label: 'Черновик', color: 'text-muted-foreground' },
  validated: { label: 'Проверен', color: 'text-emerald-500' },
  uploaded: { label: 'Загружен', color: 'text-blue-500' },
  error: { label: 'Ошибка', color: 'text-red-500' },
}

function DocumentsView() {
  const [filterStatus, setFilterStatus] = useState<ExportDoc['status'] | null>(null)
  const docs = filterStatus ? DEMO_EXPORT_DOCS.filter((d) => d.status === filterStatus) : DEMO_EXPORT_DOCS

  const counts = {
    draft: DEMO_EXPORT_DOCS.filter((d) => d.status === 'draft').length,
    validated: DEMO_EXPORT_DOCS.filter((d) => d.status === 'validated').length,
    uploaded: DEMO_EXPORT_DOCS.filter((d) => d.status === 'uploaded').length,
    error: DEMO_EXPORT_DOCS.filter((d) => d.status === 'error').length,
  }

  return (
    <div className="p-4 space-y-4">
      {/* Счётчики по статусам */}
      <div className="flex items-center gap-2">
        {([
          { key: null as ExportDoc['status'] | null, label: 'Все', count: DEMO_EXPORT_DOCS.length },
          { key: 'draft' as ExportDoc['status'], label: 'Черновики', count: counts.draft },
          { key: 'validated' as ExportDoc['status'], label: 'Проверены', count: counts.validated },
          { key: 'uploaded' as ExportDoc['status'], label: 'Загружены', count: counts.uploaded },
          { key: 'error' as ExportDoc['status'], label: 'Ошибки', count: counts.error },
        ]).map(({ key, label, count }) => (
          <button
            key={label}
            onClick={() => setFilterStatus(key)}
            className={`px-2.5 py-1 rounded text-[11px] font-medium border transition-colors ${
              filterStatus === key
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border/50 text-muted-foreground hover:border-border'
            }`}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      {/* Таблица документов */}
      <Table>
        <TableHeader>
          <TableRow className="text-[10px]">
            <TableHead className="h-7 px-2">Документ</TableHead>
            <TableHead className="h-7">Тип 1С</TableHead>
            <TableHead className="h-7">Первичный</TableHead>
            <TableHead className="h-7 text-center">v</TableHead>
            <TableHead className="h-7">Период</TableHead>
            <TableHead className="h-7 text-right">Сумма</TableHead>
            <TableHead className="h-7">Статус</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {docs.map((doc) => {
            const st = DOC_STATUS[doc.status]
            return (
              <TableRow key={doc.id} className="text-[11px]">
                <TableCell className="py-1.5 px-2">
                  <div className="flex items-center gap-1.5">
                    <FileOutput className="h-3 w-3 text-muted-foreground shrink-0" />
                    <span className="font-medium">{doc.name}</span>
                    {doc.corrected && (
                      <Badge variant="outline" className="text-[8px] h-3.5 px-1 text-amber-500 border-amber-500/30">корр.</Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="py-1.5 text-muted-foreground">{doc.type}</TableCell>
                <TableCell className="py-1.5">
                  <div className="flex items-center gap-1">
                    <FileText className="h-3 w-3 text-muted-foreground" />
                    <span className="text-muted-foreground">{doc.sourceDoc}</span>
                  </div>
                </TableCell>
                <TableCell className="py-1.5 text-center">
                  <div className="flex items-center justify-center gap-0.5">
                    {doc.sourceVersion > 1 && <GitBranch className="h-2.5 w-2.5 text-primary" />}
                    <span className={doc.sourceVersion > 1 ? 'text-primary font-medium' : 'text-muted-foreground'}>
                      v{doc.sourceVersion}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="py-1.5">{doc.period}</TableCell>
                <TableCell className="py-1.5 text-right font-mono text-xs">{doc.amount}</TableCell>
                <TableCell className="py-1.5">
                  <span className={`text-[10px] font-medium ${st.color}`}>{st.label}</span>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

/* ── Предпросмотр ── */

function PreviewView() {
  return (
    <div className="p-4 space-y-4">
      <p className="text-xs text-muted-foreground">
        Просмотр документа перед загрузкой в 1С — сравнение с первичным
      </p>

      <div className="grid grid-cols-2 gap-4">
        {/* Первичный документ */}
        <Card>
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Первичный (v2)</p>
            </div>
            <div className="space-y-2 text-[11px]">
              <div className="flex justify-between"><span className="text-muted-foreground">Документ</span><span>Смена №1847</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Станция</span><span>АКАЗС Витебский</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Дата</span><span>05.04.2026</span></div>
              <div className="border-t border-border/30 pt-2" />
              <div className="flex justify-between"><span className="text-muted-foreground">АИ-92</span><span>1 245.50 л / 78 467.50 ₽</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">АИ-95</span><span>876.20 л / 58 982.50 ₽</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">ДТ</span><span>2 100.00 л / 150 000.00 ₽</span></div>
              <div className="border-t border-border/30 pt-2" />
              <div className="flex justify-between font-bold"><span>Итого</span><span>287 450.00 ₽</span></div>
            </div>
          </CardContent>
        </Card>

        {/* Документ для 1С */}
        <Card className="border-primary/30">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <FileOutput className="h-4 w-4 text-primary" />
              <p className="text-xs font-semibold uppercase tracking-wider text-primary">Для 1С</p>
              <Badge variant="outline" className="text-[8px] h-3.5 px-1 text-amber-500 border-amber-500/30 ml-auto">корр.</Badge>
            </div>
            <div className="space-y-2 text-[11px]">
              <div className="flex justify-between"><span className="text-muted-foreground">Тип</span><span>Отчёт о розничных продажах</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Склад</span><span>АЗС Витебский (розница)</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Дата</span><span>05.04.2026</span></div>
              <div className="border-t border-border/30 pt-2" />
              <div className="flex justify-between"><span className="text-muted-foreground">АИ-92 (л)</span><span>1 245.50 л / 78 467.50 ₽</span></div>
              <div className="flex justify-between bg-amber-500/5 -mx-1 px-1 rounded"><span className="text-amber-600 dark:text-amber-400">АИ-95 (л)</span><span className="text-amber-600 dark:text-amber-400">876.20 л / 58 982.50 ₽ <span className="text-[9px]">↑ корр.</span></span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">ДТ (л)</span><span>2 100.00 л / 150 000.00 ₽</span></div>
              <div className="border-t border-border/30 pt-2" />
              <div className="flex justify-between font-bold"><span>Итого</span><span>287 450.00 ₽</span></div>
              <div className="flex justify-between text-muted-foreground"><span>НДС (22%)</span><span>52 278.69 ₽</span></div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center gap-2">
        <Button size="sm" className="h-7 text-xs gap-1.5">
          <CheckCircle2 className="h-3 w-3" />
          Подтвердить
        </Button>
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
          <RotateCcw className="h-3 w-3" />
          Вернуть на корректировку
        </Button>
      </div>
    </div>
  )
}

/* ── Валидация ── */

interface ValidationCheck {
  name: string
  status: 'pass' | 'warning' | 'fail'
  details: string
}

const DEMO_CHECKS: ValidationCheck[] = [
  { name: 'Арифметика сумм', status: 'pass', details: 'Объём × Цена = Сумма — совпадает по всем строкам' },
  { name: 'НДС', status: 'pass', details: 'НДС = Сумма × 22/122 — расчёт корректен' },
  { name: 'Номенклатура', status: 'pass', details: 'Все позиции имеют соответствие в справочнике 1С' },
  { name: 'Склад', status: 'pass', details: 'Склад «АЗС Витебский» существует в 1С' },
  { name: 'Период', status: 'pass', details: 'Апрель 2026 — открытый период' },
  { name: 'Сверка с 1С', status: 'warning', details: 'Нет данных по закрытому периоду Q1 для сравнения' },
  { name: 'Дубли', status: 'pass', details: 'Документ не дублирует ранее загруженные' },
  { name: 'Проводки', status: 'pass', details: 'Дт 90.02.1 Кт 41.02 — корреспонденция допустима' },
]

const CHECK_ICON: Record<ValidationCheck['status'], { icon: typeof CheckCircle2; color: string }> = {
  pass: { icon: CheckCircle2, color: 'text-emerald-500' },
  warning: { icon: AlertTriangle, color: 'text-amber-500' },
  fail: { icon: XCircle, color: 'text-red-500' },
}

function ValidationView() {
  const passCount = DEMO_CHECKS.filter((c) => c.status === 'pass').length
  const warnCount = DEMO_CHECKS.filter((c) => c.status === 'warning').length
  const failCount = DEMO_CHECKS.filter((c) => c.status === 'fail').length

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Проверка документов перед загрузкой в 1С</p>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-emerald-500">{passCount} ✓</span>
          {warnCount > 0 && <span className="text-[10px] text-amber-500">{warnCount} ⚠</span>}
          {failCount > 0 && <span className="text-[10px] text-red-500">{failCount} ✗</span>}
        </div>
      </div>

      <div className="space-y-1">
        {DEMO_CHECKS.map((check) => {
          const { icon: Icon, color } = CHECK_ICON[check.status]
          return (
            <div key={check.name} className="flex items-start gap-2.5 py-2 border-b border-border/30 last:border-0">
              <Icon className={`h-4 w-4 ${color} shrink-0 mt-0.5`} />
              <div className="flex-1">
                <p className="text-[11px] font-medium">{check.name}</p>
                <p className="text-[10px] text-muted-foreground">{check.details}</p>
              </div>
            </div>
          )
        })}
      </div>

      <Button size="sm" className="h-7 text-xs gap-1.5">
        <ListChecks className="h-3 w-3" />
        Запустить полную проверку
      </Button>
    </div>
  )
}

/* ── Загрузка ── */

interface UploadBatch {
  id: string
  date: string
  docsCount: number
  status: 'pending' | 'uploading' | 'success' | 'partial' | 'failed'
  result: string
}

const DEMO_BATCHES: UploadBatch[] = [
  { id: '1', date: '06.04.2026 14:30', docsCount: 2, status: 'pending', result: 'Ожидает загрузки' },
  { id: '2', date: '05.04.2026 18:15', docsCount: 3, status: 'success', result: '3 документа загружены и проведены' },
  { id: '3', date: '04.04.2026 17:40', docsCount: 4, status: 'success', result: '4 документа загружены и проведены' },
  { id: '4', date: '03.04.2026 16:20', docsCount: 2, status: 'partial', result: '1 загружен, 1 ошибка (нет номенклатуры)' },
]

const BATCH_STATUS: Record<UploadBatch['status'], { label: string; color: string; icon: typeof CheckCircle2 }> = {
  pending: { label: 'Ожидает', color: 'text-muted-foreground', icon: Clock },
  uploading: { label: 'Загрузка...', color: 'text-blue-500', icon: Loader2 },
  success: { label: 'Загружено', color: 'text-emerald-500', icon: CheckCircle2 },
  partial: { label: 'Частично', color: 'text-amber-500', icon: AlertTriangle },
  failed: { label: 'Ошибка', color: 'text-red-500', icon: XCircle },
}

function UploadView() {
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Загрузка подготовленных документов в 1С</p>
        <Button size="sm" className="h-7 text-xs gap-1.5">
          <Upload className="h-3 w-3" />
          Загрузить в 1С
        </Button>
      </div>

      <div className="space-y-2">
        {DEMO_BATCHES.map((batch) => {
          const st = BATCH_STATUS[batch.status]
          return (
            <Card key={batch.id}>
              <CardContent className="p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <st.icon className={`h-4 w-4 ${st.color} shrink-0`} />
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-[11px] font-medium">{batch.date}</p>
                        <span className="text-[10px] text-muted-foreground">{batch.docsCount} док.</span>
                      </div>
                      <p className="text-[10px] text-muted-foreground">{batch.result}</p>
                    </div>
                  </div>
                  <span className={`text-[10px] font-medium ${st.color}`}>{st.label}</span>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

/* ── Анализ (пост-загрузочный) ── */

interface AnalysisCheck {
  category: string
  checks: { name: string; status: 'ok' | 'warning' | 'error'; value: string }[]
}

const DEMO_ANALYSIS: AnalysisCheck[] = [
  {
    category: 'Проводки в 1С',
    checks: [
      { name: 'Все документы проведены', status: 'ok', value: '9 из 9' },
      { name: 'Корреспонденция счетов', status: 'ok', value: 'Дт/Кт корректны' },
      { name: 'Суммы проводок', status: 'ok', value: 'Совпадают с исходными' },
    ],
  },
  {
    category: 'Остатки',
    checks: [
      { name: 'Остаток 41.01 (опт)', status: 'ok', value: '45 200 кг' },
      { name: 'Остаток 41.02 (розница)', status: 'warning', value: '-120 л АИ-95 (отрицательный)' },
      { name: 'Сальдо по контрагентам', status: 'ok', value: 'Без расхождений' },
    ],
  },
  {
    category: 'Сверка с первичными',
    checks: [
      { name: 'Объёмы реализации', status: 'ok', value: 'Δ = 0.00 л' },
      { name: 'Суммы реализации', status: 'ok', value: 'Δ = 0.00 ₽' },
      { name: 'Количество документов', status: 'ok', value: '9 = 9' },
    ],
  },
  {
    category: 'Период',
    checks: [
      { name: 'Документы в открытом периоде', status: 'ok', value: 'Апрель 2026 — открыт' },
      { name: 'Нет записей в закрытых периодах', status: 'ok', value: 'Чисто' },
    ],
  },
]

const ANALYSIS_ICON: Record<string, { icon: typeof CheckCircle2; color: string }> = {
  ok: { icon: CheckCircle2, color: 'text-emerald-500' },
  warning: { icon: AlertTriangle, color: 'text-amber-500' },
  error: { icon: XCircle, color: 'text-red-500' },
}

function AnalysisView() {
  const totalChecks = DEMO_ANALYSIS.reduce((sum, g) => sum + g.checks.length, 0)
  const okChecks = DEMO_ANALYSIS.reduce((sum, g) => sum + g.checks.filter((c) => c.status === 'ok').length, 0)
  const warnChecks = DEMO_ANALYSIS.reduce((sum, g) => sum + g.checks.filter((c) => c.status === 'warning').length, 0)

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground">Анализ после загрузки — проверка корректности в 1С</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Shield className={`h-4 w-4 ${warnChecks > 0 ? 'text-amber-500' : 'text-emerald-500'}`} />
            <span className="text-[11px] font-medium">{okChecks}/{totalChecks}</span>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
            <Search className="h-3 w-3" />
            Запустить анализ
          </Button>
        </div>
      </div>

      <div className="space-y-4">
        {DEMO_ANALYSIS.map((group) => (
          <div key={group.category}>
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">{group.category}</p>
            <div className="space-y-0.5">
              {group.checks.map((check) => {
                const { icon: Icon, color } = ANALYSIS_ICON[check.status]
                return (
                  <div key={check.name} className="flex items-center gap-2.5 py-1.5">
                    <Icon className={`h-3.5 w-3.5 ${color} shrink-0`} />
                    <span className="text-[11px] flex-1">{check.name}</span>
                    <span className={`text-[11px] font-mono ${check.status === 'ok' ? 'text-muted-foreground' : check.status === 'warning' ? 'text-amber-500' : 'text-red-500'}`}>
                      {check.value}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-border/50 bg-muted/30 p-3">
        <p className="text-[11px] text-muted-foreground">
          <strong>Замыкание цикла:</strong> Все загруженные документы проверены.
          Проводки соответствуют первичным данным. Отрицательный остаток АИ-95 на 41.02 — норма для АЗС (недопоставка, ожидается ТТН).
        </p>
      </div>
    </div>
  )
}

/* ── Главный компонент ── */

export function ExportLayerPanel() {
  const [tab, setTab] = useState<ExportTab>('documents')

  return (
    <CentralPanelLayout items={EXPORT_MENU} activeKey={tab} onSelect={(k) => setTab(k as ExportTab)}>
      <ScrollArea className="h-full">
        {tab === 'documents' && <DocumentsView />}
        {tab === 'preview' && <PreviewView />}
        {tab === 'validation' && <ValidationView />}
        {tab === 'upload' && <UploadView />}
        {tab === 'analysis' && <AnalysisView />}
      </ScrollArea>
    </CentralPanelLayout>
  )
}
