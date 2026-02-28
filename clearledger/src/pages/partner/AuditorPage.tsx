/**
 * AuditorPage — AI-аудитор ClearLedger.
 * 2-панельный layout (WorkPanel | Tabs) по образцу LocationWorkspacePage из TSupport.
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { nanoid } from 'nanoid'
import type { PanelImperativeHandle } from 'react-resizable-panels'
import {
  LayoutDashboard,
  Cpu,
  Bot,
  Terminal as TerminalIcon,
  ScrollText,
  PanelRightClose,
  TicketCheck,
  MessageSquare,
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle2,
  Server,
  Play,
  Loader2,
  Send,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { WorkPanel } from '@/components/common/WorkPanel'
import { cn } from '@/lib/utils'

import type { ChatMessage, AIModel, AuditDashboard, FindingSeverity } from '@/types/auditor'
import { MODEL_LABELS, COMMAND_GROUPS, COMMAND_PROMPTS } from '@/types/auditor'
import * as auditorService from '@/services/auditorService'

// ---- Severity helpers ----

const SEVERITY_STYLES: Record<FindingSeverity, { bg: string; text: string; icon: typeof AlertTriangle }> = {
  critical: { bg: 'bg-red-100 dark:bg-red-900/30', text: 'text-red-700 dark:text-red-400', icon: AlertCircle },
  warning: { bg: 'bg-amber-100 dark:bg-amber-900/30', text: 'text-amber-700 dark:text-amber-400', icon: AlertTriangle },
  info: { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-700 dark:text-blue-400', icon: Info },
}

// ============================================================
// Inline Components
// ============================================================

// ---- AuditOverview (Tab: Обзор) ----

function AuditOverview() {
  const { data: dashboard, isLoading } = useQuery<AuditDashboard>({
    queryKey: ['auditor', 'dashboard'],
    queryFn: () => auditorService.getDashboard(),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!dashboard) return null

  const kpis = [
    { label: 'Критические', value: dashboard.findings.critical, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-950/40', icon: AlertCircle },
    { label: 'Предупреждения', value: dashboard.findings.warning, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-950/40', icon: AlertTriangle },
    { label: 'Информация', value: dashboard.findings.info, color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-950/40', icon: Info },
    { label: 'Решено', value: dashboard.findings.resolved, color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-950/40', icon: CheckCircle2 },
  ]

  return (
    <div className="p-4 space-y-4 overflow-y-auto h-full">
      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {kpis.map((kpi) => (
          <div key={kpi.label} className={cn('rounded-lg p-3 border', kpi.bg)}>
            <div className="flex items-center gap-2 mb-1">
              <kpi.icon className={cn('size-4', kpi.color)} />
              <span className="text-xs text-slate-600 dark:text-slate-400">{kpi.label}</span>
            </div>
            <div className={cn('text-2xl font-bold', kpi.color)}>{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* Instances */}
      <div className="rounded-lg border p-3">
        <div className="flex items-center gap-2 mb-2">
          <Server className="size-4 text-slate-500" />
          <span className="text-sm font-medium">Инстансы</span>
        </div>
        <div className="text-sm text-slate-600 dark:text-slate-400">
          Активных: <span className="font-medium text-foreground">{dashboard.instances.active}</span> из {dashboard.instances.total}
        </div>
      </div>

      {/* Recent findings */}
      <div>
        <h3 className="text-sm font-medium mb-2">Последние находки</h3>
        <div className="space-y-2">
          {dashboard.recentFindings.map((finding) => {
            const style = SEVERITY_STYLES[finding.severity]
            const Icon = style.icon
            return (
              <div key={finding.id} className={cn('rounded-lg border p-3', style.bg)}>
                <div className="flex items-start gap-2">
                  <Icon className={cn('size-4 mt-0.5 shrink-0', style.text)} />
                  <div className="min-w-0">
                    <div className={cn('text-sm font-medium', style.text)}>{finding.title}</div>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{finding.description}</p>
                    <span className="text-[10px] text-slate-400 mt-1 block">
                      {new Date(finding.timestamp).toLocaleString('ru-RU')}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ---- AuditSkills (Tab: Навыки) ----

interface AuditSkillsProps {
  instanceId: string
  onResultForAI: (result: string) => void
}

function AuditSkills({ instanceId, onResultForAI }: AuditSkillsProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(COMMAND_GROUPS.map((g) => g.id)))
  const [runningSkill, setRunningSkill] = useState<string | null>(null)
  const [skillResult, setSkillResult] = useState<string | null>(null)
  const [skillError, setSkillError] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  const toggleGroup = (groupId: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }

  const runSkill = useCallback((cmdId: string) => {
    // Abort previous
    if (controllerRef.current) controllerRef.current.abort()

    setRunningSkill(cmdId)
    setSkillResult(null)
    setSkillError(null)

    let accumulated = ''

    const ctrl = auditorService.streamAudit(
      COMMAND_PROMPTS[cmdId] ?? cmdId,
      instanceId,
      'claude-sonnet',
      (chunk, done) => {
        if (done) {
          setRunningSkill(null)
          if (accumulated) {
            setSkillResult(accumulated)
            onResultForAI(accumulated)
          }
        } else {
          accumulated += chunk
          setSkillResult(accumulated)
        }
      },
    )

    controllerRef.current = ctrl
  }, [instanceId, onResultForAI])

  return (
    <div className="p-4 space-y-3 overflow-y-auto h-full">
      {COMMAND_GROUPS.map((group) => {
        const isExpanded = expandedGroups.has(group.id)
        return (
          <div key={group.id} className="rounded-lg border">
            <button
              onClick={() => toggleGroup(group.id)}
              className="flex items-center gap-2 w-full px-3 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800 rounded-t-lg transition-colors"
            >
              {isExpanded ? <ChevronDown className="size-4 text-slate-400" /> : <ChevronRight className="size-4 text-slate-400" />}
              <span className="text-sm font-medium">{group.label}</span>
              <span className="text-xs text-slate-400 ml-auto">{group.items.length}</span>
            </button>

            {isExpanded && (
              <div className="border-t divide-y">
                {group.items.map((item) => {
                  const isRunning = runningSkill === item.id
                  return (
                    <div key={item.id} className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">{item.label}</div>
                          <p className="text-xs text-slate-500 mt-0.5">{item.description}</p>
                        </div>
                        <button
                          onClick={() => runSkill(item.id)}
                          disabled={runningSkill !== null}
                          className={cn(
                            'shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                            isRunning
                              ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                              : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700',
                            runningSkill !== null && !isRunning && 'opacity-50 cursor-not-allowed'
                          )}
                        >
                          {isRunning ? (
                            <Loader2 className="size-3 animate-spin" />
                          ) : (
                            <Play className="size-3" />
                          )}
                          {isRunning ? 'Работает...' : 'Запустить'}
                        </button>
                      </div>

                      {/* Inline result */}
                      {skillResult && (runningSkill === item.id || (!runningSkill && skillResult)) && runningSkill === item.id && (
                        <div className="mt-2 p-2 rounded bg-slate-50 dark:bg-slate-800 text-xs whitespace-pre-wrap max-h-60 overflow-y-auto">
                          {skillResult}
                          {isRunning && <span className="animate-pulse">▊</span>}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}

      {/* Global result (shown after skill finishes) */}
      {!runningSkill && skillResult && (
        <div className="rounded-lg border p-3">
          <h4 className="text-sm font-medium mb-2">Результат</h4>
          <div className="text-xs whitespace-pre-wrap text-slate-700 dark:text-slate-300 max-h-80 overflow-y-auto">
            {skillResult}
          </div>
        </div>
      )}

      {skillError && (
        <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 p-3">
          <p className="text-xs text-red-600">{skillError}</p>
        </div>
      )}
    </div>
  )
}

// ---- AuditChat (Tab: AI Чат) ----

interface AuditChatProps {
  instanceId: string
  additionalContext?: string
}

function AuditChat({ instanceId, additionalContext }: AuditChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [model, setModel] = useState<AIModel>('claude-sonnet')
  const scrollRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<AbortController | null>(null)

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const sendMessage = useCallback(() => {
    const text = input.trim()
    if (!text || isStreaming) return

    // Add user message
    const userMsg: ChatMessage = {
      id: nanoid(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsStreaming(true)

    // Add empty assistant message
    const assistantId = nanoid()
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, assistantMsg])

    // Stream response
    const ctrl = auditorService.streamAudit(
      text,
      instanceId,
      model,
      (chunk, done) => {
        if (done) {
          setIsStreaming(false)
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + chunk } : m
            )
          )
        }
      },
      additionalContext,
    )

    controllerRef.current = ctrl
  }, [input, isStreaming, instanceId, model, additionalContext])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Model selector */}
      <div className="flex items-center gap-2 px-3 py-2 border-b">
        <span className="text-xs text-slate-500">Модель:</span>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value as AIModel)}
          className="text-xs rounded border bg-white dark:bg-slate-800 dark:border-slate-700 px-2 py-1"
        >
          {Object.entries(MODEL_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2">
            <Bot className="size-8" />
            <p className="text-sm">AI-аудитор готов к работе</p>
            <p className="text-xs">Задайте вопрос или выберите навык</p>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={cn(
              'flex gap-2',
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            )}
          >
            <div
              className={cn(
                'max-w-[85%] rounded-lg px-3 py-2 text-sm',
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-foreground'
              )}
            >
              <div className="whitespace-pre-wrap break-words">{msg.content}</div>
              {msg.role === 'assistant' && isStreaming && messages[messages.length - 1]?.id === msg.id && (
                <span className="animate-pulse">▊</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Введите сообщение..."
            rows={1}
            className="flex-1 resize-none rounded-lg border px-3 py-2 text-sm bg-white dark:bg-slate-800 dark:border-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-500 max-h-32"
          />
          <button
            onClick={sendMessage}
            disabled={isStreaming || !input.trim()}
            className={cn(
              'shrink-0 p-2 rounded-lg transition-colors',
              isStreaming || !input.trim()
                ? 'bg-slate-100 text-slate-400 dark:bg-slate-800'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            )}
          >
            {isStreaming ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- Placeholder tab ----

function PlaceholderTab() {
  return (
    <div className="flex items-center justify-center h-full text-slate-400 text-sm">
      В разработке
    </div>
  )
}

// ============================================================
// Tab definitions for collapsed icon sidebar
// ============================================================

const TAB_DEFS = [
  { icon: LayoutDashboard, label: 'Обзор', tab: 'overview' },
  { icon: Cpu, label: 'Навыки', tab: 'skills' },
  { icon: Bot, label: 'AI Чат', tab: 'chat' },
  { icon: TerminalIcon, label: 'Терминал', tab: 'terminal' },
  { icon: ScrollText, label: 'Журнал', tab: 'log' },
] as const

// ============================================================
// AuditorPage — Main Component
// ============================================================

export function AuditorPage() {
  const [activeTab, setActiveTab] = useState('overview')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [selectedInstanceId, setSelectedInstanceId] = useState('inst-1')
  const [aiContext, setAiContext] = useState('')

  const leftPanelRef = useRef<PanelImperativeHandle>(null)
  const rightPanelRef = useRef<PanelImperativeHandle>(null)

  // Instances
  const { data: instances } = useQuery({
    queryKey: ['auditor', 'instances'],
    queryFn: () => auditorService.getInstances(),
  })

  const handleResultForAI = useCallback((result: string) => {
    setAiContext((prev) => prev ? `${prev}\n\n---\n\n${result}` : result)
  }, [])

  return (
    <div className="h-[calc(100vh-3.5rem)] flex flex-col">
      <div className="flex-1 min-h-0">
        <TooltipProvider delayDuration={100}>
          <ResizablePanelGroup orientation="horizontal" id="auditor-panels">
            {/* ── Левая панель: Заявки + Чаты ── */}
            <ResizablePanel
              panelRef={leftPanelRef}
              defaultSize={25}
              minSize={15}
              maxSize={40}
              collapsible
              collapsedSize={3}
              onResize={(size) => {
                const collapsed = size.asPercentage <= 3
                setLeftCollapsed(collapsed)
              }}
            >
              {leftCollapsed ? (
                <div
                  className="h-full flex flex-col items-center py-3 gap-3 bg-slate-800/30 cursor-pointer"
                  onClick={() => leftPanelRef.current?.expand()}
                >
                  {[
                    { icon: TicketCheck, label: 'Заявки' },
                    { icon: MessageSquare, label: 'Чаты' },
                  ].map(({ icon: Icon, label }) => (
                    <Tooltip key={label}>
                      <TooltipTrigger asChild>
                        <div className="p-1.5 rounded text-slate-400 hover:text-white transition-colors">
                          <Icon className="w-4 h-4" />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="right" className="text-xs">{label}</TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              ) : (
                <WorkPanel
                  panelId="auditor"
                  onCollapse={() => leftPanelRef.current?.collapse()}
                />
              )}
            </ResizablePanel>

            <ResizableHandle withHandle />

            {/* ── Правая панель: вкладки ── */}
            <ResizablePanel
              panelRef={rightPanelRef}
              defaultSize={75}
              minSize={20}
              collapsible
              collapsedSize={3}
              onResize={(size) => {
                const collapsed = size.asPercentage <= 3
                setRightCollapsed(collapsed)
              }}
            >
              {rightCollapsed ? (
                <div
                  className="h-full flex flex-col items-center py-3 gap-2 bg-slate-800/30 cursor-pointer"
                  onClick={() => rightPanelRef.current?.expand()}
                >
                  {TAB_DEFS.map(({ icon: Icon, label, tab }) => (
                    <Tooltip key={tab}>
                      <TooltipTrigger asChild>
                        <div className={cn(
                          'p-1.5 rounded transition-colors',
                          activeTab === tab ? 'text-white bg-white/10' : 'text-slate-400 hover:text-white'
                        )}>
                          <Icon className="w-4 h-4" />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="left" className="text-xs">{label}</TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              ) : (
                <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full flex flex-col">
                  {/* ── Tab bar header (тёмная полоса как в LocationWorkspacePage) ── */}
                  <div className="px-3 py-2 shrink-0 flex items-center gap-2 border-b border-slate-600 bg-slate-800/50">
                    <TabsList className="h-9 flex-1 bg-slate-700/80 p-1 gap-0.5">
                      <TabsTrigger value="overview" className="text-xs gap-1.5 px-2.5 data-[state=active]:bg-blue-600/20 data-[state=active]:text-blue-400">
                        <LayoutDashboard className="w-3.5 h-3.5" />Обзор
                      </TabsTrigger>
                      <TabsTrigger value="skills" className="text-xs gap-1.5 px-2.5 data-[state=active]:bg-blue-600/20 data-[state=active]:text-blue-400">
                        <Cpu className="w-3.5 h-3.5" />Навыки
                      </TabsTrigger>
                      <TabsTrigger value="chat" className="text-xs gap-1.5 px-2.5 data-[state=active]:bg-blue-600/20 data-[state=active]:text-blue-400">
                        <Bot className="w-3.5 h-3.5" />AI Чат
                      </TabsTrigger>
                      <TabsTrigger value="terminal" className="text-xs gap-1.5 px-2.5 data-[state=active]:bg-blue-600/20 data-[state=active]:text-blue-400">
                        <TerminalIcon className="w-3.5 h-3.5" />Терминал
                      </TabsTrigger>
                      <TabsTrigger value="log" className="text-xs gap-1.5 px-2.5 data-[state=active]:bg-blue-600/20 data-[state=active]:text-blue-400">
                        <ScrollText className="w-3.5 h-3.5" />Журнал
                      </TabsTrigger>
                    </TabsList>

                    {/* Instance selector */}
                    <select
                      value={selectedInstanceId}
                      onChange={(e) => setSelectedInstanceId(e.target.value)}
                      className="text-xs rounded border border-slate-600 bg-slate-700 text-slate-200 px-2 py-1.5 max-w-48 truncate shrink-0"
                    >
                      {(instances ?? []).map((inst) => (
                        <option key={inst.id} value={inst.id}>{inst.name}</option>
                      ))}
                    </select>

                    {/* Collapse right panel */}
                    <button
                      onClick={() => rightPanelRef.current?.collapse()}
                      className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors shrink-0"
                      title="Свернуть вкладки"
                    >
                      <PanelRightClose className="w-4 h-4" />
                    </button>
                  </div>

                  {/* ── Tab content ── */}
                  <div className="flex-1 min-h-0">
                    <TabsContent value="overview" className="h-full m-0">
                      <AuditOverview />
                    </TabsContent>

                    <TabsContent value="skills" className="h-full m-0">
                      <AuditSkills
                        instanceId={selectedInstanceId}
                        onResultForAI={handleResultForAI}
                      />
                    </TabsContent>

                    <TabsContent value="chat" className="h-full m-0">
                      <AuditChat
                        instanceId={selectedInstanceId}
                        additionalContext={aiContext}
                      />
                    </TabsContent>

                    <TabsContent value="terminal" className="h-full m-0">
                      <PlaceholderTab />
                    </TabsContent>

                    <TabsContent value="log" className="h-full m-0">
                      <PlaceholderTab />
                    </TabsContent>
                  </div>
                </Tabs>
              )}
            </ResizablePanel>
          </ResizablePanelGroup>
        </TooltipProvider>
      </div>
    </div>
  )
}
