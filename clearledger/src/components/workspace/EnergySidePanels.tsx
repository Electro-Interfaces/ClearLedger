/**
 * Боковые слои рабочей области для energy-профиля (ЭЗС):
 * - EnergyRawPanel — слой ВХОДЯЩИХ ДОКУМЕНТОВ (L1 RAW): проводник с поиском/фильтром,
 *   каталогами (папки по источникам) и файлами. Аналог фуел-RawPanel, но без смен/ТТН/1С.
 * - EnergyExportDocsPanel — слой ДОКУМЕНТОВ ДЛЯ ЗАГРУЗКИ (L3) → учётная система компании.
 * Демо на DEMO_EZS.
 */
import { useState, useMemo, type ReactNode } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  FileText, FileOutput, CheckCircle2, Clock, Upload, Search,
  ChevronRight, ChevronDown, Folder, FolderOpen,
} from 'lucide-react'
import { toast } from 'sonner'
import { DEMO_EZS, sumRelease, tariffCheck, fmtN } from '@/components/balance/balanceCalc'

const sessions = DEMO_EZS.reduce((a, s) => a + tariffCheck(s).sessions, 0)
const revenue = DEMO_EZS.reduce((a, s) => a + sumRelease(s).rub, 0)
const ezsCount = DEMO_EZS.length

type DocStatus = 'accepted' | 'processing' | 'ready'
const STATUS: Record<DocStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  accepted: { label: 'принято', cls: 'text-emerald-600 dark:text-emerald-400', Icon: CheckCircle2 },
  processing: { label: 'в обработке', cls: 'text-amber-600 dark:text-amber-400', Icon: Clock },
  ready: { label: 'готов', cls: 'text-emerald-600 dark:text-emerald-400', Icon: CheckCircle2 },
}

/* ── Слой входящих документов (L1 RAW): каталоги (папки) → файлы ── */
interface RawFile { name: string; label: string; date: string; status: DocStatus; meta: string }
interface RawFolder { source: string; files: RawFile[] }

const INPUT_TREE: RawFolder[] = [
  { source: 'ПК ezs.rushydro.ru', files: [
    { name: 'sessions_2026-06-23.json', label: 'Сессии зарядки', date: '23.06.2026', status: 'accepted', meta: `${fmtN(sessions)} сессий` },
    { name: 'payments_2026-06-23.csv', label: 'Реестр платежей', date: '23.06.2026', status: 'accepted', meta: `${fmtN(revenue)} ₽` },
    { name: 'ul_report_2026-06.xlsx', label: 'Отчёт по ЮЛ', date: '23.06.2026', status: 'processing', meta: 'постоплата' },
    { name: 'rfid_bindings.json', label: 'RFID-привязки', date: '23.06.2026', status: 'accepted', meta: 'карты/метки' },
  ] },
  { source: 'Банк-эквайер', files: [
    { name: 'statement_T1.csv', label: 'Выписка зачислений', date: '23.06.2026', status: 'accepted', meta: 'T+1' },
    { name: 'holds.csv', label: 'Реестр холдов', date: '23.06.2026', status: 'processing', meta: 'холд<факт' },
  ] },
  { source: 'ОФД', files: [
    { name: 'z_reports_2026-06-23.xml', label: 'Z-отчёты', date: '23.06.2026', status: 'accepted', meta: `${ezsCount} ЭЗС` },
    { name: 'receipts_2026-06-23.xml', label: 'Чеки (54-ФЗ)', date: '23.06.2026', status: 'accepted', meta: 'фискальные' },
  ] },
  { source: 'Поставщик э/э', files: [
    { name: 'invoice_2026-06.pdf', label: 'Счёт за электроэнергию', date: '20.06.2026', status: 'processing', meta: 'к закупке' },
    { name: 'meters_2026-06.csv', label: 'Показания ПУ', date: '23.06.2026', status: 'accepted', meta: 'суточные' },
  ] },
]
const TOTAL_FILES = INPUT_TREE.reduce((a, f) => a + f.files.length, 0)

export function EnergyRawPanel({ hideHeader, collapseButton }: { hideHeader?: boolean; collapseButton?: ReactNode }) {
  const [q, setQ] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())

  const tree = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return INPUT_TREE
    return INPUT_TREE
      .map((f) => ({ ...f, files: f.files.filter((x) => (x.label + ' ' + x.name).toLowerCase().includes(needle)) }))
      .filter((f) => f.files.length > 0)
  }, [q])

  const toggle = (src: string) =>
    setCollapsed((prev) => { const n = new Set(prev); n.has(src) ? n.delete(src) : n.add(src); return n })

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-border/50 px-3 py-2">
        <h2 className="truncate text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          {hideHeader ? `Входящие · ${TOTAL_FILES}` : 'Входящие документы'}
        </h2>
        {collapseButton}
      </div>

      {/* Поиск / фильтр */}
      <div className="border-b border-border/40 p-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по документам…" className="h-7 pl-7 text-xs" />
        </div>
      </div>

      {/* Каталоги (папки) → файлы */}
      <ScrollArea className="flex-1">
        <div className="p-1.5">
          {tree.length === 0 && <p className="px-2 py-4 text-center text-xs text-muted-foreground">Ничего не найдено</p>}
          {tree.map((folder) => {
            const open = !collapsed.has(folder.source)
            return (
              <div key={folder.source} className="mb-0.5">
                <button
                  onClick={() => toggle(folder.source)}
                  className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left hover:bg-accent/40"
                >
                  {open ? <ChevronDown className="size-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-3 shrink-0 text-muted-foreground" />}
                  {open ? <FolderOpen className="size-3.5 shrink-0 text-primary/70" /> : <Folder className="size-3.5 shrink-0 text-muted-foreground" />}
                  <span className="flex-1 truncate text-xs font-medium">{folder.source}</span>
                  <Badge variant="outline" className="text-[9px]">{folder.files.length}</Badge>
                </button>
                {open && (
                  <div className="ml-3 border-l border-border/40 pl-1.5">
                    {folder.files.map((file) => {
                      const st = STATUS[file.status]
                      return (
                        <button
                          key={file.name}
                          onClick={() => toast.info(`${file.label} · ${file.name}`)}
                          className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-accent/40"
                          title={file.name}
                        >
                          <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-xs">{file.label}</div>
                            <div className="truncate text-[10px] text-muted-foreground">{file.date} · {file.meta}</div>
                          </div>
                          <st.Icon className={`size-3.5 shrink-0 ${st.cls}`} />
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </ScrollArea>
      <div className="border-t border-border/50 px-3 py-1.5 text-[10px] text-muted-foreground/60">демо-данные · L1 → нормализуется в L2</div>
    </div>
  )
}

/* ── Слой документов для загрузки (L3) ── */
const OUTPUT_DOCS: { name: string; meta: string; status: DocStatus }[] = [
  { name: 'Акт об оказании услуг зарядки', meta: `${ezsCount} ЭЗС · период`, status: 'ready' },
  { name: 'Счёт на оплату (ЮЛ)', meta: 'корп. клиенты', status: 'ready' },
  { name: 'Реестр зарядных сессий', meta: `${fmtN(sessions)} строк`, status: 'ready' },
  { name: 'Счёт-фактура', meta: 'НДС 22%', status: 'ready' },
]

export function EnergyExportDocsPanel({ hideHeader }: { hideHeader?: boolean }) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {!hideHeader && (
        <div className="border-b border-border/50 px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Для учётной системы</h2>
        </div>
      )}
      <ScrollArea className="flex-1">
        <div className="space-y-1 p-2">
          {OUTPUT_DOCS.map((d) => {
            const st = STATUS[d.status]
            return (
              <div key={d.name} className="flex items-center gap-2 rounded-md border border-border/40 bg-background/40 px-2 py-2">
                <FileOutput className="size-3.5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium">{d.name}</div>
                  <div className="truncate text-[10px] text-muted-foreground">{d.meta}</div>
                </div>
                <Badge variant="secondary" className={`gap-1 text-[10px] ${st.cls}`}><st.Icon className="size-3" />{st.label}</Badge>
              </div>
            )
          })}
        </div>
      </ScrollArea>
      <div className="space-y-1.5 border-t border-border/50 p-2">
        <Button size="sm" className="w-full gap-1.5" onClick={() => toast.success('Документы выгружены в учётную систему компании (демо)')}>
          <Upload className="size-3.5" /> Выгрузить в учётную систему
        </Button>
        <p className="text-center text-[10px] text-muted-foreground/60">слой L3 · демо-данные</p>
      </div>
    </div>
  )
}
