/**
 * Построение виртуальной файловой системы «Документы» из каталога компании.
 *
 * Источники (по убыванию приоритета):
 *  1. API + fuel-профиль — реальные документы БД: смены (/api/fuel/shifts)
 *     и ТТН (/api/fuel/receipts).
 *  2. API + office-профиль — первичка из бухгалтерии (/api/books/docs):
 *     у компании без объектов документы приезжают не сменами, а учётом.
 *  3. API + прочие профили — реальные загрузки: каналы компании и история
 *     их прогонов (/api/channels + /channels/{id}/runs).
 *  4. Без API — localStorage-прототип (`getAllLoadedDocs`).
 * У каждого документа готовый путь `catalog` (напр. `/Нефтепродукты АЗС/Смены/
 * {станция}/{год}-{месяц}/`). Дерево строится РОВНО по этим путям — папки =
 * сегменты пути, листья = документы.
 */

import { useMemo, useCallback, useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { getAllLoadedDocs, type LoadedDocument } from '@/services/channelSyncService'
import {
  getLoadedShifts, getLoadedReceipts,
  type LoadedShift, type LoadedReceipt,
} from '@/services/fuel/fuelMappingService'
import { loadChannels, getChannelRuns, type ChannelRun } from '@/services/channelService'
import { getAllDocs, type DocRow } from '@/services/booksService'
import type { Channel } from '@/types/channel'
import { format } from 'date-fns'
import type { ShiftRecord } from '@/services/fuel/types'
import type { FsNode, RawPanelFilters, SortConfig } from './raw-panel-types'

function safeFmt(iso: string | undefined, withTime = true): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return format(d, withTime ? 'dd.MM.yyyy HH:mm' : 'dd.MM.yyyy')
}

/** Иконочный тип узла по backend-типу документа. */
function iconType(docType: string): FsNode['docType'] {
  if (docType === 'shift_report') return 'shift'
  if (docType === 'delivery' || docType === 'receipt') return 'delivery'
  return undefined
}

/** Человекочитаемый тип документа (колонка «Тип», как в проводнике). */
export function docTypeLabel(docType: string): string {
  const map: Record<string, string> = {
    shift_report: 'Сменный отчёт',
    receipt: 'Поступление (ТТН)',
    delivery: 'Поступление (ТТН)',
    price: 'Цены',
    sts_transactions: 'Операции отпуска',
    sts_coupons: 'Купоны/талоны',
    sts_tanks: 'Остатки резервуаров',
    msto_transactions: 'Онлайн-заказы',
    corp_transactions: 'Корп. карты',
    channel_run: 'Загрузка данных',
  }
  return map[docType] ?? 'Документ'
}

/* ── маппинг серверных сущностей БД → LoadedDocument ── */

const fmtInt = (v: number | null | undefined) => Math.round(v ?? 0).toLocaleString('ru-RU')

function ym(iso: string | null | undefined): string {
  if (!iso) return 'Без даты'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'Без даты' : format(d, 'yyyy-MM')
}

function shiftToDoc(s: LoadedShift): LoadedDocument {
  const station = s.station_name ?? `АЗС-${s.station_code}`
  const date = s.opened_at ?? s.created_at
  return {
    id: s.id, channelId: '', streamId: '', docType: 'shift_report', origin: 'api',
    fingerprint: s.id,
    title: `Смена №${s.shift_number} — ${station}`,
    stationId: s.station_code,
    date, data: s,
    catalog: `Нефтепродукты АЗС/Смены/${station}/${ym(date)}`,
    loadedAt: s.created_at,
  }
}

function receiptToDoc(r: LoadedReceipt): LoadedDocument {
  const supplier = r.supplier?.trim() || 'Поставщик не указан'
  const date = r.received_at ?? r.created_at
  return {
    id: r.id, channelId: '', streamId: '', docType: 'receipt', origin: 'api',
    fingerprint: r.id,
    title: `ТТН ${r.ttn} — ${r.fuel_name}`,
    stationId: r.station_code,
    date, data: r,
    catalog: `Нефтепродукты АЗС/Поступления (ТТН)/${supplier}/${ym(date)}`,
    loadedAt: r.created_at,
  }
}

function runToDoc(ch: Channel, run: ChannelRun): LoadedDocument {
  const dt = run.started_at ? format(new Date(run.started_at), 'dd.MM.yyyy HH:mm') : '—'
  return {
    id: run.id, channelId: ch.id, streamId: '', docType: 'channel_run', origin: 'api',
    fingerprint: run.id,
    title: `Загрузка ${dt} — ${fmtInt(run.loaded)} записей`,
    stationId: 0,
    date: run.started_at ?? '', data: run,
    catalog: `Каналы/${ch.name}`,
    loadedAt: run.finished_at ?? run.started_at ?? '',
  }
}

const RUN_STATUS_LABEL: Record<string, string> = {
  success: 'Успешно', partial: 'Частично', error: 'Ошибка', running: 'Идёт…',
}

/**
 * Документ бухгалтерии в узел проводника. Раскладка утверждена МАГом:
 * участок учёта → вид документа → год → месяц. Ключ пути включает порядковый
 * номер: пара «номер + дата» в 1С не уникальна (два документа №1-2212 от 22.12.2023).
 */
const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

function bookDocToDoc(row: DocRow, sectionTitle: string, i: number): LoadedDocument {
  // Дата приходит строкой `ГГГГ-ММ-ДД` — разбираем её как строку, а не через Date:
  // разбор датой у отрицательных часовых поясов уводит первое число в прошлый месяц.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(row.date ?? '')
  const period = m ? `${m[1]}/${MONTHS[Number(m[2]) - 1]}` : 'Без даты'
  const shown = m ? `${m[3]}.${m[2]}.${m[1]}` : '—'
  const who = row.counterparty?.trim() || 'Без контрагента'
  return {
    id: `${row.type}-${i}`,
    channelId: '', streamId: '', docType: row.type, origin: 'api',
    fingerprint: `${row.type}|${row.date}|${row.number}|${row.inn ?? ''}`,
    title: `№ ${row.number || 'б/н'} от ${shown} — ${who}`,
    stationId: 0,
    date: row.date, data: row,
    catalog: `${sectionTitle}/${row.label}/${period}`,
    loadedAt: row.date,
  }
}

/** Статус документа учёта: как в 1С («Проведён»/«Не проведён») плюс замок закрытого месяца. */
function bookDocStatus(row: DocRow): string {
  return row.periodStatus === 'closed' ? `${row.status} 🔒` : row.status
}

/** «Размер» документа в терминах предметной области (литры/записи). */
function docSize(doc: LoadedDocument): string {
  if (doc.origin !== 'api') return '—'
  if (doc.docType === 'shift_report') return `${fmtInt((doc.data as LoadedShift).total_liters)} л`
  if (doc.docType === 'receipt') return `${fmtInt((doc.data as LoadedReceipt).doc_volume_liters)} л`
  if (doc.docType === 'channel_run') return `${fmtInt((doc.data as ChannelRun).loaded)} зап.`
  if (isBookDoc(doc)) return `${fmtInt((doc.data as DocRow).amount)} ₽`
  return '—'
}

/** Документ учёта (шапка из бухгалтерии) — у него в `data` лежит строка реестра. */
function isBookDoc(doc: LoadedDocument): boolean {
  return doc.origin === 'api' && !!(doc.data as DocRow)?.label && !!(doc.data as DocRow)?.status
}

/** Метка статуса файла-узла (превью/колонка «Статус»). */
function docStatus(doc: LoadedDocument): string | undefined {
  if (doc.docType === 'shift_report') {
    if (doc.origin === 'api') return (doc.data as LoadedShift).closed_at ? 'Закрыта' : 'Открыта'
    return (doc.data as ShiftRecord)?.status === 'closed' ? 'Закрыта' : 'Открыта'
  }
  if (doc.docType === 'channel_run') return RUN_STATUS_LABEL[(doc.data as ChannelRun).status] ?? (doc.data as ChannelRun).status
  if (isBookDoc(doc)) return bookDocStatus(doc.data as DocRow)
  return undefined
}

/** Открыта ли смена (для фильтра «открытые/закрытые» обоих происхождений). */
function isShiftOpen(doc: LoadedDocument): boolean {
  if (doc.origin === 'api') return !(doc.data as LoadedShift).closed_at
  return (doc.data as ShiftRecord)?.status !== 'closed'
}

export function useRawPanelTree(filters: RawPanelFilters, sortConfig: SortConfig) {
  const queryClient = useQueryClient()
  const { stationCode } = useFilters()
  const { company } = useCompany()

  const apiMode = isApiEnabled()
  const apiFuel = apiMode && company.profileId === 'fuel'
  // Компания без объектов: первичка приезжает из бухгалтерии, а не сменами и ТТН.
  const apiBooks = apiMode && company.profileId === 'office'
  const apiRuns = apiMode && !apiFuel && !apiBooks

  // Без API — localStorage-прототип (перечитать при монтировании: данные
  // могли пополниться в другом разделе).
  const [localDocs, setLocalDocs] = useState<LoadedDocument[]>(() => (apiMode ? [] : getAllLoadedDocs()))
  const [dataUpdatedAt, setDataUpdatedAt] = useState<number>(() => Date.now())
  useEffect(() => {
    if (!apiMode) {
      setLocalDocs(getAllLoadedDocs())
      setDataUpdatedAt(Date.now())
    }
  }, [apiMode])

  // Полное хранилище, не «последние N» — лимиты эндпоинтов подняты параметром.
  const shiftsQ = useQuery({
    queryKey: ['raw-docs-shifts', company.id],
    enabled: apiFuel,
    queryFn: () => getLoadedShifts({ limit: 20000 }),
    staleTime: 60_000,
  })
  const receiptsQ = useQuery({
    queryKey: ['raw-docs-receipts', company.id],
    enabled: apiFuel,
    queryFn: () => getLoadedReceipts(20000),
    staleTime: 60_000,
  })
  const booksQ = useQuery({
    queryKey: ['raw-docs-books', company.id],
    enabled: apiBooks,
    queryFn: async () => {
      const { rows, sections } = await getAllDocs(company.id)
      const title = new Map(sections.map((s) => [s.code, s.title]))
      return rows.map((r, i) => bookDocToDoc(r, title.get(r.section ?? '') ?? 'Прочее', i))
    },
    staleTime: 60_000,
  })
  const runsQ = useQuery({
    queryKey: ['raw-docs-runs', company.id],
    enabled: apiRuns,
    queryFn: async () => {
      const channels = await loadChannels(company.id)
      const perChannel = await Promise.all(channels.map(async (ch) => {
        try {
          return (await getChannelRuns(ch.id)).map((run) => runToDoc(ch, run))
        } catch {
          return [] as LoadedDocument[]
        }
      }))
      return perChannel.flat()
    },
    staleTime: 60_000,
  })

  const docs = useMemo<LoadedDocument[]>(() => {
    if (apiFuel) {
      return [
        ...(shiftsQ.data ?? []).map(shiftToDoc),
        ...(receiptsQ.data ?? []).map(receiptToDoc),
      ]
    }
    if (apiBooks) return booksQ.data ?? []
    if (apiRuns) return runsQ.data ?? []
    return localDocs
  }, [apiFuel, apiBooks, apiRuns, shiftsQ.data, receiptsQ.data, booksQ.data, runsQ.data, localDocs])

  const fsTree = useMemo(() => {
    const tree = new Map<string, FsNode[]>()

    // ── фильтрация документов ──
    let filtered = docs
    if (stationCode !== 'all') {
      const code = Number(stationCode)
      filtered = filtered.filter((d) => d.stationId === code)
    }
    if (filters.docType === 'shifts') filtered = filtered.filter((d) => d.docType === 'shift_report')
    if (filters.docType === 'receipts') filtered = filtered.filter((d) => d.docType === 'delivery' || d.docType === 'receipt')
    if (filters.status === 'open') filtered = filtered.filter((d) => d.docType !== 'shift_report' || isShiftOpen(d))
    if (filters.status === 'closed') filtered = filtered.filter((d) => d.docType === 'shift_report' && !isShiftOpen(d))
    const q = filters.searchQuery.trim().toLowerCase()
    if (q) filtered = filtered.filter((d) => d.title.toLowerCase().includes(q) || d.catalog.toLowerCase().includes(q))

    // ── построение дерева по catalog-путям ──
    const ensureFolder = (parentKey: string, name: string, path: string) => {
      const siblings = tree.get(parentKey) ?? []
      if (!siblings.some((n) => n.type === 'folder' && n.path === path)) {
        siblings.push({ name, type: 'folder', path, childCount: 0 })
        tree.set(parentKey, siblings)
      }
    }

    for (const doc of filtered) {
      const segs = doc.catalog.split('/').map((s) => s.trim()).filter(Boolean)
      let parentKey = ''
      let pathAcc = ''
      for (const seg of segs) {
        pathAcc = pathAcc ? `${pathAcc}/${seg}` : seg
        ensureFolder(parentKey, seg, pathAcc)
        parentKey = pathAcc
      }
      // Лист-документ в конечной папке. path уникален по id документа.
      const fileNode: FsNode = {
        name: doc.title || 'Документ',
        type: 'file',
        path: `${parentKey}/#${doc.id}`,
        doc,
        stationId: doc.stationId,
        docType: iconType(doc.docType),
        date: safeFmt(doc.date || doc.loadedAt),
        status: docStatus(doc),
        size: docSize(doc),
        typeText: isBookDoc(doc) ? (doc.data as DocRow).label : undefined,
      }
      const files = tree.get(parentKey) ?? []
      files.push(fileNode)
      tree.set(parentKey, files)
    }

    // childCount = число прямых детей каждой папки (как в проводнике).
    for (const [, nodes] of tree) {
      for (const n of nodes) {
        if (n.type === 'folder') n.childCount = (tree.get(n.path) ?? []).length
      }
    }

    return tree
  }, [docs, stationCode, filters])

  // Плоский отсортированный список файлов (вид «Список»/«Таблица»).
  const flatFiles = useMemo(() => {
    const files: FsNode[] = []
    for (const [, nodes] of fsTree) {
      for (const node of nodes) if (node.type === 'file') files.push(node)
    }
    files.sort((a, b) => {
      const dir = sortConfig.direction === 'asc' ? 1 : -1
      switch (sortConfig.column) {
        case 'name':
          return dir * a.name.localeCompare(b.name, 'ru')
        case 'date': {
          const da = a.doc?.date || a.doc?.loadedAt || ''
          const db = b.doc?.date || b.doc?.loadedAt || ''
          return dir * da.localeCompare(db)
        }
        case 'status':
          return dir * (a.status || '').localeCompare(b.status || '')
        default:
          return 0
      }
    })
    return files
  }, [fsTree, sortConfig])

  const totalItemCount = useMemo(() => flatFiles.length, [flatFiles])

  const handleRefresh = useCallback(() => {
    if (apiMode) {
      queryClient.invalidateQueries({ queryKey: ['raw-docs-shifts'] })
      queryClient.invalidateQueries({ queryKey: ['raw-docs-receipts'] })
      queryClient.invalidateQueries({ queryKey: ['raw-docs-books'] })
      queryClient.invalidateQueries({ queryKey: ['raw-docs-runs'] })
    } else {
      queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
      queryClient.invalidateQueries({ queryKey: ['sts-all-receipts'] })
      setLocalDocs(getAllLoadedDocs())
    }
    setDataUpdatedAt(Date.now())
  }, [apiMode, queryClient])

  return {
    fsTree,
    flatFiles,
    isLoading: apiFuel ? (shiftsQ.isLoading || receiptsQ.isLoading)
      : apiBooks ? booksQ.isLoading : apiRuns ? runsQ.isLoading : false,
    isFetching: apiFuel ? (shiftsQ.isFetching || receiptsQ.isFetching)
      : apiBooks ? booksQ.isFetching : apiRuns ? runsQ.isFetching : false,
    totalItemCount,
    dataUpdatedAt,
    handleRefresh,
  }
}

/** Build flat list of visible nodes from tree + expandedPaths */
export function buildVisibleList(
  fsTree: Map<string, FsNode[]>,
  expandedPaths: string[],
): { node: FsNode; depth: number }[] {
  const result: { node: FsNode; depth: number }[] = []

  function walk(parentKey: string, depth: number) {
    const nodes = fsTree.get(parentKey)
    if (!nodes) return
    for (const node of nodes) {
      result.push({ node, depth })
      if (node.type === 'folder' && expandedPaths.includes(node.path)) {
        walk(node.path, depth + 1)
      }
    }
  }

  walk('', 0)
  return result
}
