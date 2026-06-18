/**
 * «Окно станции» (cockpit) — модалка по точке обслуживания.
 * Вкладки: Паспорт / Статус / Сервис / Договоры / Документы / Финансы / Сверки.
 * Рабочие сейчас: Паспорт (свойства+редактирование), Операционный статус
 * (смена+история), Договоры (реальная связь), HubEx-связка во вкладке Сервис.
 * Остальное — информативные заглушки (будущие модули).
 */
import { useEffect, useState, type ReactNode, type ComponentType } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Pencil, Loader2, Wrench, Building, FileSignature, FileText, Wallet, GitCompare, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { useLocationContracts } from '@/hooks/useReferences'
import {
  setOperationalStatus, getOperationalStatusHistory, getHubexTasks,
} from '@/services/locationService'
import { MetadataFieldsReader } from '@/components/manual/MetadataFieldsReader'
import { resolveLocationIcon } from '@/components/locationTypes/locationIcons'
import { LOCATION_STATUS_META, type ServiceLocation } from '@/types/location'

const OP_META: Record<string, { label: string; cls: string }> = {
  working: { label: 'Работает', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  not_working: { label: 'Не работает', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  on_repair: { label: 'На ремонте', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  maintenance: { label: 'Обслуживание', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  unknown: { label: 'Неизвестно', cls: 'bg-muted text-muted-foreground' },
}
const OP_OPTIONS = ['working', 'not_working', 'on_repair', 'maintenance', 'unknown']

function Placeholder({ icon: Icon, title, text }: { icon: ComponentType<{ className?: string }>; title: string; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 text-muted-foreground">
      <Icon className="h-10 w-10 mb-3 opacity-40" />
      <p className="font-medium text-foreground/80">{title}</p>
      <p className="text-sm max-w-md mt-1">{text}</p>
    </div>
  )
}

export function LocationCockpitModal({
  location,
  onClose,
  onChanged,
  renderEdit,
}: {
  location: ServiceLocation | null
  onClose: () => void
  onChanged?: () => void
  /** Триггер редактирования паспорта (оборачивает кнопку в LocationEditDialog). */
  renderEdit?: (location: ServiceLocation, child: ReactNode) => ReactNode
}) {
  const types = useLocationTypes()
  const qc = useQueryClient()
  const locId = location?.id ?? null

  const contractsQ = useLocationContracts(locId)
  const historyQ = useQuery({
    queryKey: ['op-status-history', locId],
    queryFn: () => getOperationalStatusHistory(locId!),
    enabled: !!locId,
  })
  const hubexQ = useQuery({
    queryKey: ['hubex-tasks', locId],
    queryFn: () => getHubexTasks(locId!),
    enabled: !!locId,
    staleTime: 60_000,
  })

  const [opStatus, setOpStatus] = useState('unknown')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setOpStatus(location?.operationalStatus ?? 'unknown')
    setReason('')
  }, [location?.id, location?.operationalStatus])

  if (!location) return null

  const typeDef = types.find((t) => t.code === location.type)
  const meta = (location.metadata ?? {}) as Record<string, unknown>
  const Icon = resolveLocationIcon(typeDef?.icon)
  const curOp = location.operationalStatus ?? 'unknown'
  const lifeMeta = LOCATION_STATUS_META[location.status]
  const isFuel = location.type === 'fuel_station'

  async function applyStatus() {
    if (opStatus === curOp && !reason.trim()) {
      toast.info('Статус не изменён')
      return
    }
    setSaving(true)
    try {
      await setOperationalStatus(location!.id, opStatus, reason.trim() || undefined)
      toast.success('Операционный статус обновлён')
      setReason('')
      await qc.invalidateQueries({ queryKey: ['op-status-history', location!.id] })
      onChanged?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сменить статус')
    } finally {
      setSaving(false)
    }
  }

  const contracts = contractsQ.data?.contracts ?? []

  return (
    <Dialog open={!!location} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="!max-w-none !w-[100vw] !h-[100vh] !rounded-none !p-0 flex flex-col gap-0">
        {/* Шапка */}
        <DialogHeader className="px-5 py-3 border-b border-border/50 space-y-0">
          <DialogTitle className="flex items-center gap-3 text-lg flex-wrap">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-muted shrink-0">
              <Icon className="h-4 w-4 text-muted-foreground" />
            </span>
            <span>{location.name}</span>
            <span className="font-mono text-sm text-muted-foreground">
              {String(meta.number ?? location.code)}
            </span>
            <Badge variant="secondary">{typeDef?.name ?? location.type}</Badge>
            {lifeMeta && <Badge variant="outline" className="text-[11px]">{lifeMeta.label}</Badge>}
            <Badge variant="secondary" className={`text-[11px] ${OP_META[curOp]?.cls ?? ''}`}>
              {OP_META[curOp]?.label ?? curOp}
            </Badge>
          </DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="passport" className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="px-3 h-auto justify-start overflow-x-auto rounded-none bg-transparent border-b border-border/50 shrink-0">
            <TabsTrigger value="passport">Паспорт</TabsTrigger>
            <TabsTrigger value="status">Статус</TabsTrigger>
            <TabsTrigger value="service">Сервис</TabsTrigger>
            <TabsTrigger value="contracts">
              Договоры{contracts.length > 0 && <Badge variant="secondary" className="ml-1.5 text-[10px]">{contracts.length}</Badge>}
            </TabsTrigger>
            <TabsTrigger value="documents">Документы</TabsTrigger>
            <TabsTrigger value="finances">Финансы</TabsTrigger>
            <TabsTrigger value="reconciliation">Сверки</TabsTrigger>
          </TabsList>

          <div className="flex-1 overflow-hidden">
            {/* ── Паспорт ── */}
            <TabsContent value="passport" className="h-full m-0">
              <ScrollArea className="h-full">
                <div className="p-5 space-y-4 max-w-3xl">
                  <Card>
                    <CardContent className="pt-5 grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                      <Field label="Код / серийник" value={location.code} mono />
                      <Field label="Тип" value={typeDef?.name ?? location.type} />
                      <Field label="Жизненный статус" value={lifeMeta?.label ?? location.status} />
                      <Field label="Операц. статус" value={OP_META[curOp]?.label ?? curOp} />
                      <div className="col-span-2"><Field label="Адрес" value={location.address || '—'} /></div>
                      {location.description && (
                        <div className="col-span-2"><Field label="Описание" value={location.description} /></div>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardContent className="pt-5">
                      <div className="text-xs font-medium text-muted-foreground mb-3">
                        Свойства типа «{typeDef?.name ?? location.type}»
                      </div>
                      <MetadataFieldsReader fields={typeDef?.fields ?? []} values={meta} />
                    </CardContent>
                  </Card>

                  {renderEdit?.(location, (
                    <Button variant="outline"><Pencil className="h-4 w-4 mr-2" /> Редактировать паспорт</Button>
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* ── Операционный статус ── */}
            <TabsContent value="status" className="h-full m-0">
              <ScrollArea className="h-full">
                <div className="p-5 space-y-4 max-w-2xl">
                  <Card>
                    <CardContent className="pt-5 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-foreground">Текущий статус:</span>
                        <Badge variant="secondary" className={OP_META[curOp]?.cls}>{OP_META[curOp]?.label ?? curOp}</Badge>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-[200px_1fr] gap-3 items-end">
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
                        {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />} Применить
                      </Button>
                    </CardContent>
                  </Card>

                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-2">История изменений</div>
                    {historyQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
                    {historyQ.data && historyQ.data.length === 0 && (
                      <p className="text-sm text-muted-foreground">Изменений ещё не было.</p>
                    )}
                    <div className="space-y-1.5">
                      {historyQ.data?.map((h, i) => (
                        <div key={i} className="flex items-center gap-2 text-sm border-b border-border/30 py-1.5 flex-wrap">
                          <span className="text-xs text-muted-foreground tabular-nums">
                            {h.at ? new Date(h.at).toLocaleString('ru-RU') : ''}
                          </span>
                          <Badge variant="outline" className="text-[10px]">{OP_META[h.from ?? '']?.label ?? h.from}</Badge>
                          →
                          <Badge variant="secondary" className={`text-[10px] ${OP_META[h.to ?? '']?.cls ?? ''}`}>{OP_META[h.to ?? '']?.label ?? h.to}</Badge>
                          {h.reason && <span className="text-muted-foreground">· {h.reason}</span>}
                          <span className="text-xs text-muted-foreground ml-auto">{h.user}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </ScrollArea>
            </TabsContent>

            {/* ── Сервис (HubEx) ── */}
            <TabsContent value="service" className="h-full m-0">
              <ScrollArea className="h-full">
                <div className="p-5 space-y-4 max-w-3xl">
                  {meta.hubexAssetId == null ? (
                    <Placeholder icon={Wrench} title="Станция не связана с HubEx"
                      text="Нет HubEx asset_id — сервисные заявки недоступны. Связка проставляется при импорте реестра." />
                  ) : (
                    <>
                      <Card>
                        <CardContent className="pt-5 grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                          <Field label="HubEx asset_id" value={String(meta.hubexAssetId)} mono />
                          <Field label="Статус связки" value={String(meta.linkStatus ?? '—')} />
                          <div className="col-span-2"><Field label="HubEx название" value={String(meta.hubexName ?? '—')} /></div>
                        </CardContent>
                      </Card>

                      <div className="flex items-center justify-between">
                        <div className="text-sm font-medium">Сервисные заявки HubEx FSM</div>
                        {hubexQ.data?.configured && (
                          <span className="text-xs text-muted-foreground">всего: {hubexQ.data.total}</span>
                        )}
                      </div>

                      {hubexQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка заявок…</p>}
                      {hubexQ.data && !hubexQ.data.configured && (
                        <p className="text-sm text-muted-foreground">HubEx-интеграция не настроена (нет сервисного токена).</p>
                      )}
                      {hubexQ.data?.error && (
                        <p className="text-sm text-destructive">HubEx недоступен: {hubexQ.data.error}</p>
                      )}
                      {hubexQ.data?.configured && !hubexQ.data.error && hubexQ.data.tasks.length === 0 && (
                        <p className="text-sm text-muted-foreground">Заявок по станции нет.</p>
                      )}

                      <div className="space-y-2">
                        {hubexQ.data?.tasks.map((t) => (
                          <div key={t.id} className="rounded-md border border-border/50 p-3 space-y-1.5">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono text-xs font-medium">#{t.number}</span>
                              {t.status && (
                                <Badge variant="secondary" className="text-[10px]"
                                  style={t.statusColor ? { backgroundColor: `#${t.statusColor}26`, color: `#${t.statusColor}` } : undefined}>
                                  {t.status}
                                </Badge>
                              )}
                              {t.criticality && (
                                <Badge variant="outline" className="text-[10px]"
                                  style={t.criticalityColor ? { borderColor: `#${t.criticalityColor}`, color: `#${t.criticalityColor}` } : undefined}>
                                  {t.criticality}
                                </Badge>
                              )}
                              {t.type && <span className="text-xs text-muted-foreground">{t.type}</span>}
                            </div>
                            {t.notes && <div className="text-sm whitespace-pre-line">{t.notes.trim()}</div>}
                            <div className="flex gap-4 text-xs text-muted-foreground flex-wrap">
                              {t.assignee && <span>Исполнитель: {t.assignee}</span>}
                              {t.deadline && <span>Срок: {new Date(t.deadline).toLocaleString('ru-RU')}</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* ── Договоры ── */}
            <TabsContent value="contracts" className="h-full m-0">
              <ScrollArea className="h-full">
                <div className="p-5 space-y-3 max-w-3xl">
                  {contractsQ.isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
                  {contracts.length === 0 && !contractsQ.isLoading && (
                    <Placeholder icon={FileSignature} title="Нет связанных договоров"
                      text="Договоры (адресные на эту станцию и общекомпанейские) появятся здесь после загрузки из 1С и привязки." />
                  )}
                  {contracts.map((c) => (
                    <div key={c.id} className="flex items-start justify-between gap-3 rounded-md border border-border/50 p-3 text-sm">
                      <div className="min-w-0">
                        <div className="font-medium">{c.number}</div>
                        <div className="text-xs text-muted-foreground">
                          {c.counterpartyName || c.counterpartyId}{c.kind && <span> · {c.kind}</span>}
                        </div>
                      </div>
                      {c.companyWide
                        ? <Badge variant="secondary" className="gap-1 shrink-0 text-[10px]"><Building className="h-2.5 w-2.5" /> вся компания</Badge>
                        : <Badge variant="outline" className="shrink-0 text-[10px]">адресный</Badge>}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* ── Документы ── */}
            <TabsContent value="documents" className="h-full m-0">
              <Placeholder icon={FileText} title="Документы по станции"
                text="Привязка документов (ПТУ/ТТН/ОРП и пр.) к станции по location_id — в разработке. Сейчас документы связаны со складом, не со станцией." />
            </TabsContent>

            {/* ── Финансы ── */}
            <TabsContent value="finances" className="h-full m-0">
              <Placeholder icon={Wallet} title="Задолженности по станции"
                text="Дебиторка/кредиторка в разрезе станции появится после привязки документов к станции (сейчас долги считаются по контрагентам в целом)." />
            </TabsContent>

            {/* ── Сверки ── */}
            <TabsContent value="reconciliation" className="h-full m-0">
              {isFuel ? (
                <Placeholder icon={GitCompare} title="Сверки по станции"
                  text="Для топливной АЗС сверка по сменам/каналам ведётся в разделе «Сверки» — выберите эту станцию в фильтре." />
              ) : (
                <Placeholder icon={Zap} title="Сверка зарядных сессий"
                  text="Сверка ЭЗС по кВт·ч (сессии зарядки ↔ платежи) — будущая фаза EV-пайплайна." />
              )}
            </TabsContent>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`font-medium break-words ${mono ? 'font-mono text-xs' : ''}`}>{value}</div>
    </div>
  )
}
