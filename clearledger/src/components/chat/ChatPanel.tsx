/**
 * Внутренний чат — полный порт мессенджера Coordinator (TSupport) под стек Ledger.
 * Telegram-механика: единый список комнат, папки-группировки (Все/Группы/Личные +
 * кастомные), закреплённые сообщения, реакции, ответы, @упоминания, редактирование/
 * удаление, медиа-альбомы + Lightbox, архив, видеозвонок. REST — chatService,
 * live — useChatWs. Рендерится в InteractionHost (модалка «Взаимодействие»).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  MessageCircle, Send, Search, User as UserIcon, Building2, Users, Plus,
  ChevronLeft, ChevronRight, FileText, MoreVertical, Archive, ArchiveRestore,
  Trash2, Reply, Pencil, X, Check, Megaphone, Lock, Pin, Video, UserPlus,
  Folder, AtSign, Loader2, Paperclip, Camera, Search as SearchIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { useChatWs, type WsEvent } from '@/hooks/useChatWs'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuTrigger, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import {
  getUserColor, getDateLabel, formatTime, computeGrouping, bubbleRadius,
  type GroupingInfo,
} from './telegram-helpers'
import { AuthImage, AuthVideo, AuthFileChip, useAuthBlobUrl } from './AuthMedia'
import { RegionCapture } from './RegionCapture'
import * as chat from '@/services/chatService'
import type {
  ChatRoom, ChatMessage, ChatParticipant, ChatPresence, ChatFolder as ChatFolderModel,
} from '@/services/chatService'

// ── константы ────────────────────────────────────────────────────────────────
const QUICK_REACTIONS = ['👍', '❤️', '🔥', '😂', '😮', '👏']
const NEWS_WRITER_ROLES = new Set(['admin', 'partner', 'coordinator', 'company', 'tech'])
type FolderKey = 'all' | 'group' | 'direct'
const FOLDERS: { key: FolderKey; label: string; icon: typeof UserIcon }[] = [
  { key: 'all', label: 'Все', icon: MessageCircle },
  { key: 'group', label: 'Группы', icon: Users },
  { key: 'direct', label: 'Личные', icon: UserIcon },
]
const AVATAR_COLORS = [
  'bg-blue-600', 'bg-emerald-600', 'bg-violet-600', 'bg-rose-600',
  'bg-amber-600', 'bg-cyan-600', 'bg-indigo-600', 'bg-teal-600',
]

// ── хелперы ──────────────────────────────────────────────────────────────────
function avatarColor(seed: string): string {
  let h = 0
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) | 0
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length]
}
function initials(name?: string | null): string {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '·'
}
function fmtAge(iso: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  const m = Math.floor(ms / 60000)
  if (m < 1) return 'сейчас'
  if (m < 60) return `${m}м`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}ч`
  return `${Math.floor(h / 24)}д`
}
function roomIcon(r: { type: string; kind?: string | null }): typeof UserIcon {
  if (r.kind === 'news') return Megaphone
  if (r.kind === 'general' || r.type === 'company') return Building2
  if (r.type === 'group') return Users
  return UserIcon
}
function isImageMessage(m: ChatMessage): boolean {
  return Boolean(m.fileUrl && !m.isDeleted
    && (m.type === 'image' || /\.(jpg|jpeg|png|gif|webp)$/i.test(m.fileName || m.fileUrl)))
}
function presenceText(p?: ChatPresence & { lastSeenAt?: string | null }): string {
  if (!p) return ''
  return p.online ? 'в сети' : 'не в сети'
}

/** Подсветка @упоминаний */
function highlightMentions(text: string, keyPrefix: number): React.ReactNode {
  const parts = text.split(/(@[А-ЯЁA-Z][\wа-яёА-ЯЁ-]*(?: [А-ЯЁA-Z][\wа-яёА-ЯЁ-]*)?)/g)
  if (parts.length === 1) return text
  return parts.map((part, j) =>
    part.startsWith('@')
      ? <span key={`${keyPrefix}-${j}`} className="font-semibold text-blue-400">{part}</span>
      : part)
}
/** Ссылки + @упоминания */
function linkifyText(text: string): React.ReactNode {
  const parts = text.split(/(https?:\/\/[^\s]+)/g)
  return parts.map((part, i) =>
    /^https?:\/\//.test(part)
      ? <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="text-blue-400 underline break-all">{part}</a>
      : <span key={i}>{highlightMentions(part, i)}</span>)
}
function highlightText(text: string, query: string): React.ReactNode {
  if (!query) return text
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase()
      ? <mark key={i} className="rounded-sm bg-yellow-400/30 px-0.5 text-yellow-700 dark:text-yellow-200">{part}</mark>
      : part)
}

// ── аватар ───────────────────────────────────────────────────────────────────
function Avatar({ seed, name, icon: Icon, online, size = 40 }: {
  seed: string; name?: string | null; icon?: typeof UserIcon; online?: boolean; size?: number
}) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div className={cn('flex h-full w-full items-center justify-center rounded-full font-semibold text-white', avatarColor(seed))}
        style={{ fontSize: size * 0.4 }}>
        {Icon ? <Icon style={{ width: size * 0.5, height: size * 0.5 }} /> : initials(name)}
      </div>
      {online && <span className="absolute -bottom-px -right-px h-2.5 w-2.5 rounded-full bg-emerald-500 ring-2 ring-card" />}
    </div>
  )
}

// ── Lightbox ─────────────────────────────────────────────────────────────────
function Lightbox({ items, index, onClose, onNavigate }: {
  items: { path: string; name?: string }[]; index: number
  onClose: () => void; onNavigate: (delta: number) => void
}) {
  const item = items[index]
  const dl = useAuthBlobUrl(item?.path ?? null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') onNavigate(-1)
      if (e.key === 'ArrowRight') onNavigate(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, onNavigate])
  if (!item) return null
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/90" onClick={onClose}>
      <button onClick={onClose} className="absolute right-3 top-3 rounded-full bg-slate-800/80 p-2 text-slate-300 hover:text-white" title="Закрыть (Esc)">
        <X className="size-4" />
      </button>
      {dl && (
        <a href={dl} download={item.name || 'изображение'} onClick={(e) => e.stopPropagation()}
          className="absolute right-14 top-3 rounded-full bg-slate-800/80 p-2 text-slate-300 hover:text-white" title="Скачать">
          <FileText className="size-4" />
        </a>
      )}
      {index > 0 && (
        <button onClick={(e) => { e.stopPropagation(); onNavigate(-1) }} className="absolute left-3 rounded-full bg-slate-800/80 p-2 text-slate-300 hover:text-white" title="Предыдущее (←)">
          <ChevronLeft className="size-5" />
        </button>
      )}
      <AuthImage path={item.path} alt={item.name} className="max-h-[92vh] max-w-[92vw] object-contain" />
      {index < items.length - 1 && (
        <button onClick={(e) => { e.stopPropagation(); onNavigate(1) }} className="absolute right-3 rounded-full bg-slate-800/80 p-2 text-slate-300 hover:text-white" title="Следующее (→)">
          <ChevronRight className="size-5" />
        </button>
      )}
      <span className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-slate-800/80 px-3 py-1 text-xs text-slate-300">
        {index + 1} из {items.length}{item.name ? ` · ${item.name}` : ''}
      </span>
    </div>
  )
}

// ── панель информации о комнате (участники) ──────────────────────────────────
function RoomInfoPanel({ room, participants, userId, canManage, onAdd, onMessageUser, presenceMap }: {
  room?: ChatRoom
  participants?: ChatParticipant[]
  userId?: string
  canManage: boolean
  onAdd: (uid: string) => void
  onMessageUser: (uid: string) => void
  presenceMap: Map<string, ChatPresence>
}) {
  const [q, setQ] = useState('')
  const { data: found = [] } = useQuery({
    queryKey: ['chat-user-search', q],
    queryFn: () => chat.searchUsers(q),
    enabled: canManage,
  })
  const memberIds = new Set((participants || []).map((p) => p.userId))
  const addable = found.filter((u) => !memberIds.has(u.userId))
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3">
      <div className="mb-3">
        <div className="mb-1 text-xs font-semibold text-muted-foreground">Участники · {participants?.length ?? 0}</div>
        <div className="space-y-0.5">
          {(participants || []).map((p) => {
            const online = presenceMap.get(p.userId)?.online || p.online
            return (
              <div key={p.userId} className="flex items-center gap-2.5 rounded-md px-1.5 py-1.5 hover:bg-accent">
                <Avatar seed={p.userId} name={p.name} online={online} size={32} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{p.name}{p.userId === userId && ' (вы)'}</div>
                  <div className="text-[11px] text-muted-foreground">{p.role === 'admin' ? 'админ' : 'участник'}</div>
                </div>
                {p.userId !== userId && room?.type !== 'direct' && (
                  <button onClick={() => onMessageUser(p.userId)} className="rounded p-1 text-muted-foreground hover:text-foreground" title="Написать лично">
                    <MessageCircle className="size-4" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
      {canManage && room?.type !== 'direct' && (
        <div>
          <div className="mb-1 text-xs font-semibold text-muted-foreground">Добавить участника</div>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск сотрудника…" className="h-8 pl-8 text-xs" />
          </div>
          <div className="space-y-0.5">
            {addable.map((u) => (
              <button key={u.userId} onClick={() => onAdd(u.userId)} className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left hover:bg-accent">
                <Avatar seed={u.userId} name={u.name} online={u.online} size={30} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{u.name}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{u.email}</div>
                </div>
                <Plus className="size-4 shrink-0 text-primary" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── диалог создания чата (личный / группа) ────────────────────────────────────
function CreateChatDialog({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; onCreated: (roomId: string) => void
}) {
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [groupName, setGroupName] = useState('')
  const [busy, setBusy] = useState(false)
  const { data: users = [] } = useQuery({
    queryKey: ['chat-user-search', q],
    queryFn: () => chat.searchUsers(q),
    enabled: open,
  })
  const ids = Object.keys(picked)
  const isGroup = ids.length > 1
  useEffect(() => { if (!open) { setQ(''); setPicked({}); setGroupName('') } }, [open])
  async function create() {
    if (!ids.length) return
    setBusy(true)
    try {
      const room = isGroup
        ? await chat.createRoom('group', ids, groupName.trim() || `Группа (${ids.length + 1})`)
        : await chat.createRoom('direct', ids)
      onCreated(room.id)
      onOpenChange(false)
    } catch { toast.error('Не удалось создать чат') } finally { setBusy(false) }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm gap-0 p-0 sm:max-w-sm">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-base">Новый чат</DialogTitle>
        </DialogHeader>
        <div className="p-3">
          {isGroup && (
            <Input placeholder="Название группы" value={groupName} onChange={(e) => setGroupName(e.target.value)} className="mb-2 h-8" />
          )}
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Поиск сотрудника…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8" />
          </div>
          {ids.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {ids.map((id) => (
                <button key={id} onClick={() => setPicked((p) => { const n = { ...p }; delete n[id]; return n })}
                  className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20">
                  {picked[id]} ✕
                </button>
              ))}
            </div>
          )}
          <div className="max-h-64 min-h-[8rem] overflow-y-auto">
            {users.map((u) => (
              <button key={u.userId} onClick={() => setPicked((p) => (p[u.userId] ? (() => { const n = { ...p }; delete n[u.userId]; return n })() : { ...p, [u.userId]: u.name }))}
                className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-accent">
                <Avatar seed={u.userId} name={u.name} online={u.online} size={32} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{u.name}</div>
                  <div className="truncate text-xs text-muted-foreground">{u.email}</div>
                </div>
                {picked[u.userId] && <Check className="size-4 shrink-0 text-primary" />}
              </button>
            ))}
            {users.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">Никого не найдено</p>}
          </div>
          <Button className="mt-3 w-full" disabled={!ids.length || busy} onClick={create}>
            {busy && <Loader2 className="mr-1 size-3.5 animate-spin" />}
            {isGroup ? 'Создать группу' : 'Открыть чат'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── бабл сообщения ────────────────────────────────────────────────────────────
function ChatBubble({
  message, album, isOwn, grouping, canDelete, editingId, editText, searchHighlight,
  onReply, onEditStart, onEditCancel, onEditSave, onEditTextChange, onDelete,
  onAuthorClick, onReact, onPin, onImageClick,
}: {
  message: ChatMessage
  album?: ChatMessage[]
  isOwn: boolean
  grouping: GroupingInfo
  canDelete: boolean
  editingId: string | null
  editText: string
  searchHighlight?: string
  onReply: () => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onEditTextChange: (t: string) => void
  onDelete: () => void
  onAuthorClick?: () => void
  onReact?: (emoji: string) => void
  onPin?: () => void
  onImageClick?: (path: string) => void
}) {
  const { isFirstInGroup, isLastInGroup, showDate } = grouping
  const isImage = isImageMessage(message)
  const isVideo = message.fileUrl && !message.isDeleted
    && (message.type === 'video' || /\.(mp4|webm|mov|m4v)$/i.test(message.fileName || message.fileUrl))
  const isEditing = editingId === message.id

  if (message.isDeleted) {
    return (
      <>
        {showDate && <DateChip iso={message.createdAt} />}
        <div className={cn('flex', isOwn ? 'justify-end' : 'justify-start', isLastInGroup ? 'mb-2' : 'mb-[2px]')}>
          <div className={cn('max-w-[85%] px-2.5 py-1.5', bubbleRadius(isOwn, isFirstInGroup, isLastInGroup), 'bg-muted/50')}>
            <p className="text-[11px] italic text-muted-foreground">Сообщение удалено</p>
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      {showDate && <DateChip iso={message.createdAt} />}
      <div className={cn('group/bubble flex', isOwn ? 'justify-end' : 'justify-start', isLastInGroup ? 'mb-2' : 'mb-[2px]')}>
        <div className={cn(
          'relative max-w-[85%] px-2.5 py-1.5',
          bubbleRadius(isOwn, isFirstInGroup, isLastInGroup),
          isOwn ? 'bg-primary text-primary-foreground' : 'bg-muted',
        )}>
          {/* Меню действий: hover на мыши, всегда видно на тач-устройствах */}
          <div className={cn(
            'absolute -top-3 z-10 flex items-center gap-0.5 rounded-md border border-border bg-popover px-0.5 py-0.5 shadow-lg opacity-0 transition-opacity group-hover/bubble:opacity-100 [@media(pointer:coarse)]:opacity-100',
            isOwn ? 'right-0' : 'left-0',
          )}>
            {onReact && QUICK_REACTIONS.map((emoji) => (
              <button key={emoji} onClick={() => onReact(emoji)} className="rounded px-0.5 text-[13px] leading-none hover:bg-accent" title={emoji}>{emoji}</button>
            ))}
            {onReact && <span className="mx-0.5 h-3 w-px bg-border" />}
            <button onClick={onReply} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" title="Ответить"><Reply className="size-3" /></button>
            {onPin && <button onClick={onPin} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" title="Закрепить"><Pin className="size-3" /></button>}
            {isOwn && <button onClick={onEditStart} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" title="Редактировать"><Pencil className="size-3" /></button>}
            {canDelete && <button onClick={onDelete} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-red-500" title="Удалить"><Trash2 className="size-3" /></button>}
          </div>

          {!isOwn && isFirstInGroup && (
            <button type="button" onClick={onAuthorClick} disabled={!onAuthorClick}
              title={onAuthorClick ? 'Написать лично' : undefined}
              className={cn('mb-0.5 block text-left text-[10px] font-semibold', getUserColor(message.userId || ''), onAuthorClick && 'cursor-pointer hover:underline')}>
              {message.userName || 'Пользователь'}
            </button>
          )}

          {message.replyTo && message.replyPreview && (
            <div className="mb-1 rounded-r border-l-2 border-blue-500 pl-1.5">
              <div className="text-[9px] font-medium text-blue-400">{message.replyAuthor || 'Пользователь'}</div>
              <div className="max-w-[200px] truncate text-[10px] opacity-70">{message.replyPreview}</div>
            </div>
          )}

          {isEditing ? (
            <div className="space-y-1">
              <textarea autoFocus value={editText} onChange={(e) => onEditTextChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onEditSave() }
                  if (e.key === 'Escape') onEditCancel()
                }}
                className="min-h-[28px] w-full resize-none rounded border border-border bg-transparent p-1 text-xs outline-none focus:border-primary" rows={2} />
              <div className="flex justify-end gap-1">
                <button onClick={onEditCancel} className="rounded p-0.5 text-muted-foreground hover:bg-accent"><X className="size-3.5" /></button>
                <button onClick={onEditSave} className="rounded p-0.5 text-emerald-500 hover:bg-accent"><Check className="size-3.5" /></button>
              </div>
            </div>
          ) : (
            message.content && (
              <p className="whitespace-pre-wrap break-words text-xs">
                {searchHighlight ? highlightText(message.content, searchHighlight) : linkifyText(message.content)}
                <span className={cn('inline-block', isOwn ? 'w-16' : 'w-11')} />
              </p>
            )
          )}

          {/* Медиа */}
          {album ? (
            <div className="mt-1 grid w-[min(240px,60vw)] grid-cols-2 gap-0.5 overflow-hidden rounded-lg">
              {album.slice(0, 4).map((it, k) => (
                <button key={it.id} type="button" onClick={() => onImageClick?.(it.fileUrl!)}
                  className={cn('relative block', album.length === 3 && k === 0 && 'col-span-2')}>
                  <AuthImage path={it.fileUrl!} alt={it.fileName || ''} className={cn('w-full object-cover', album.length === 3 && k === 0 ? 'h-[120px]' : 'h-[100px]')} />
                  {k === 3 && album.length > 4 && (
                    <span className="absolute inset-0 flex items-center justify-center bg-black/60 text-sm font-semibold text-white">+{album.length - 4}</span>
                  )}
                </button>
              ))}
            </div>
          ) : message.fileUrl ? (
            isVideo ? (
              <AuthVideo path={message.fileUrl} className="mt-1 max-w-[280px] rounded" />
            ) : isImage ? (
              <button type="button" className="mt-1 block" onClick={() => onImageClick?.(message.fileUrl!)}>
                <AuthImage path={message.fileUrl} alt={message.fileName || 'Изображение'} className="max-h-[180px] max-w-[240px] rounded object-cover" />
              </button>
            ) : (
              <AuthFileChip path={message.fileUrl} name={message.fileName} size={message.fileSize} mine={isOwn} />
            )
          ) : null}

          {/* Реакции */}
          {message.reactions.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {message.reactions.map((r) => (
                <button key={r.emoji} onClick={() => onReact?.(r.emoji)}
                  className={cn('inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[11px] leading-4 transition-colors',
                    r.mine ? 'border-blue-500/60 bg-blue-500/20 text-blue-500 dark:text-blue-200' : 'border-border bg-background/60 text-muted-foreground hover:border-foreground/30')}>
                  {r.emoji}<span className="text-[9px] tabular-nums">{r.count}</span>
                </button>
              ))}
            </div>
          )}

          <span className={cn('absolute bottom-1 right-2 flex items-center gap-0.5 text-[10px]', isOwn ? 'text-primary-foreground/60' : 'text-muted-foreground/70')}>
            {message.isEdited && <span className="text-[9px] opacity-70">ред.</span>}
            {formatTime(message.createdAt)}
            {isOwn && (
              <span className={cn('text-[9px]', message.readCount > 0 && 'text-sky-300')}
                title={message.readCount > 0 ? `Прочитали: ${message.readCount}` : 'Отправлено'}>
                {message.readCount > 0 ? '✓✓' : '✓'}
              </span>
            )}
          </span>
        </div>
      </div>
    </>
  )
}

function DateChip({ iso }: { iso: string }) {
  return (
    <div className="my-2 flex justify-center">
      <span className="rounded-full bg-muted px-3 py-1 text-[11px] text-muted-foreground">{getDateLabel(iso)}</span>
    </div>
  )
}

/** Превью прикреплённого (ещё не отправленного) файла: миниатюра для картинок. */
function PendingThumb({ file, onRemove }: { file: File; onRemove: () => void }) {
  const isImg = file.type.startsWith('image/')
  const url = useMemo(() => (isImg ? URL.createObjectURL(file) : null), [file, isImg])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  return (
    <span className="relative inline-flex items-center gap-1 rounded bg-muted px-1 py-0.5 text-[10px]">
      {url ? <img src={url} alt={file.name} className="size-9 rounded object-cover" /> : <FileText className="mx-1 size-3.5" />}
      <span className="max-w-[90px] truncate pr-0.5">{file.name}</span>
      <button onClick={onRemove} className="text-muted-foreground hover:text-red-500" title="Убрать"><X className="size-3" /></button>
    </span>
  )
}

// ── корневой компонент ────────────────────────────────────────────────────────
export function ChatPanel({ compact }: { compact?: boolean } = {}) {
  const { user } = useAuth()
  const isMobile = useIsMobile()
  // Узкий контейнер (правый док) — одна колонка список↔переписка + папки-чипы,
  // даже на десктопе: 3 колонки в ~420px не помещаются.
  const singleColumn = isMobile || !!compact
  const qc = useQueryClient()

  const [selectedRoom, setSelectedRoom] = useState<string | null>(null)
  const [messageText, setMessageText] = useState('')
  const [messageSearch, setMessageSearch] = useState('')
  const [showMessageSearch, setShowMessageSearch] = useState(false)
  const [listSearch, setListSearch] = useState('')
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [showRoomInfo, setShowRoomInfo] = useState(false)
  const [folder, setFolder] = useState<string>('all')
  const [lightbox, setLightbox] = useState<{ items: { path: string; name?: string }[]; index: number } | null>(null)
  const [folderDialogOpen, setFolderDialogOpen] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [typingUsers, setTypingUsers] = useState<Map<string, string>>(new Map())

  const mentionMapRef = useRef<Map<string, string>>(new Map())
  const dragFolderRef = useRef<string | null>(null)
  const typingTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const lastTypingRef = useRef(0)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const endRef = useRef<HTMLDivElement>(null)

  // ── данные ──
  const { data: rooms = [] } = useQuery({
    queryKey: ['chat-rooms', showArchived],
    queryFn: () => chat.getRooms(showArchived),
    refetchInterval: 60000,
  })
  const { data: messages = [] } = useQuery({
    queryKey: ['chat-messages', selectedRoom, messageSearch],
    queryFn: () => chat.getMessages(selectedRoom!, messageSearch || undefined),
    enabled: !!selectedRoom,
    staleTime: 0,
  })
  const { data: roomDetail } = useQuery({
    queryKey: ['chat-room-detail', selectedRoom],
    queryFn: () => chat.getRoom(selectedRoom!),
    enabled: !!selectedRoom,
  })
  const { data: folders = [] } = useQuery({
    queryKey: ['chat-folders'],
    queryFn: () => chat.getFolders(),
  })
  const { data: presence = [] } = useQuery({
    queryKey: ['chat-presence'],
    queryFn: () => chat.getPresence(),
    refetchInterval: 60000,
  })
  const presenceMap = useMemo(() => new Map(presence.map((p) => [p.userId, p])), [presence])

  // ── WebSocket ──
  const onWs = useCallback((e: WsEvent) => {
    switch (e.type) {
      case 'chat:message':
        qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] })
        qc.invalidateQueries({ queryKey: ['chat-rooms'] })
        break
      case 'chat:read':
      case 'chat:reaction':
      case 'message:edited':
      case 'message:deleted':
        qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] })
        break
      case 'chat:pin':
      case 'room:archived':
        qc.invalidateQueries({ queryKey: ['chat-rooms'] })
        qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] })
        break
      case 'presence':
        qc.invalidateQueries({ queryKey: ['chat-presence'] })
        break
      case 'chat:mention':
        toast.info(`${e.fromName || 'Кто-то'} упомянул вас в «${e.roomName || 'чате'}»`, { description: e.preview as string })
        qc.invalidateQueries({ queryKey: ['chat-rooms'] })
        break
      case 'chat:typing':
        if (e.userId !== user?.id && e.channel === `chat:${selectedRoom}`) {
          const uid = e.userId as string
          setTypingUsers((prev) => new Map(prev).set(uid, (e.userName as string) || 'Пользователь'))
          const t = typingTimersRef.current.get(uid)
          if (t) clearTimeout(t)
          typingTimersRef.current.set(uid, setTimeout(() => {
            setTypingUsers((prev) => { const n = new Map(prev); n.delete(uid); return n })
            typingTimersRef.current.delete(uid)
          }, 3000))
        }
        break
    }
  }, [qc, selectedRoom, user?.id])

  const channels = useMemo(() => (selectedRoom ? [`chat:${selectedRoom}`] : []), [selectedRoom])
  const { sendTyping } = useChatWs(channels, onWs)

  // ── мутации ──
  const sendMutation = useMutation({
    mutationFn: async (content: string) => {
      let uploaded: { fileUrl: string; fileName: string; fileSize: number }[] = []
      if (pendingFiles.length && selectedRoom) {
        setUploading(true)
        try {
          uploaded = await Promise.all(pendingFiles.map((f) => chat.uploadAttachment(f, user?.default_company_id)))
        } finally { setUploading(false) }
      }
      const typeOf = (name: string) =>
        /\.(jpg|jpeg|png|gif|webp)$/i.test(name) ? 'image'
          : /\.(mp4|webm|mov|m4v)$/i.test(name) ? 'video' : 'file'
      const mentions = Array.from(mentionMapRef.current.entries())
        .filter(([name]) => content.includes(`@${name}`)).map(([, id]) => id)
      const first = await chat.sendMessage(selectedRoom!, {
        content,
        type: uploaded[0] ? typeOf(uploaded[0].fileName) : undefined,
        fileUrl: uploaded[0]?.fileUrl,
        fileName: uploaded[0]?.fileName,
        fileSize: uploaded[0]?.fileSize,
        replyTo: replyTo?.id,
        mentions: mentions.length ? mentions : undefined,
      })
      for (const f of uploaded.slice(1)) {
        await chat.sendMessage(selectedRoom!, { content: '', type: typeOf(f.fileName), fileUrl: f.fileUrl, fileName: f.fileName, fileSize: f.fileSize })
      }
      return first
    },
    onSuccess: () => {
      setMessageText(''); setPendingFiles([]); setReplyTo(null); setMentionQuery(null)
      mentionMapRef.current.clear()
      qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] })
      qc.invalidateQueries({ queryKey: ['chat-rooms'] })
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось отправить'),
  })

  const editMutation = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) => chat.editMessage(selectedRoom!, id, content),
    onSuccess: () => { setEditingId(null); setEditText(''); qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] }) },
    onError: (err: Error) => toast.error(err.message || 'Не удалось изменить'),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => chat.deleteMessage(selectedRoom!, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] }),
    onError: (err: Error) => toast.error(err.message || 'Не удалось удалить'),
  })
  const reactMutation = useMutation({
    mutationFn: ({ id, emoji }: { id: string; emoji: string }) => chat.reactMessage(selectedRoom!, id, emoji),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] }),
    onError: () => toast.error('Не удалось поставить реакцию'),
  })
  const pinMutation = useMutation({
    mutationFn: (id: string | null) => chat.pinMessage(selectedRoom!, id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }) },
    onError: (err: Error) => toast.error(err.message || 'Не удалось закрепить'),
  })
  const callMutation = useMutation({
    mutationFn: async () => {
      const url = `https://meet.jit.si/TradeLedger-chat-${selectedRoom!.replaceAll('-', '')}`
      window.open(url, '_blank', 'noopener,noreferrer')
      return chat.sendMessage(selectedRoom!, { content: `📹 ${user?.name || 'Участник'} приглашает в видеозвонок — присоединяйтесь: ${url}` })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] }),
  })
  const openDirectMutation = useMutation({
    mutationFn: (uid: string) => chat.createRoom('direct', [uid]),
    onSuccess: (room) => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); setSelectedRoom(room.id); setShowRoomInfo(false) },
    onError: () => toast.error('Не удалось открыть личный чат'),
  })
  const createFolderMutation = useMutation({
    mutationFn: (name: string) => chat.createFolder(name),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['chat-folders'] })
      setFolderDialogOpen(false); setNewFolderName(''); setFolder(created.id)
    },
    onError: () => toast.error('Не удалось создать папку'),
  })

  // ── эффекты ──
  useEffect(() => {
    if (selectedRoom) chat.markRead(selectedRoom).then(() => qc.invalidateQueries({ queryKey: ['chat-rooms'] })).catch(() => {})
  }, [selectedRoom, messages.length, qc])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length, typingUsers])

  // ── действия ──
  const handleSend = () => {
    const t = messageText.trim()
    if ((!t && !pendingFiles.length) || !selectedRoom || sendMutation.isPending || uploading) return
    sendMutation.mutate(t)
  }
  const handleTextChange = (val: string) => {
    setMessageText(val)
    const m = val.match(/@([\wа-яА-ЯёЁ-]*)$/)
    setMentionQuery(m ? m[1] : null)
    if (selectedRoom && val.trim()) {
      const now = Date.now()
      if (now - lastTypingRef.current > 2000) { lastTypingRef.current = now; sendTyping(`chat:${selectedRoom}`) }
    }
  }
  // Вставка скриншота из буфера (Win+Shift+S → Ctrl+V): изображение → вложение
  const handlePaste = (e: React.ClipboardEvent) => {
    const imgs = Array.from(e.clipboardData?.items || [])
      .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
      .map((it) => it.getAsFile())
      .filter((f): f is File => !!f)
    if (!imgs.length) return
    e.preventDefault()
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
    const named = imgs.map((f, i) =>
      new File([f], f.name && !/^image\.\w+$/i.test(f.name) ? f.name : `Скриншот-${stamp}${i ? `-${i}` : ''}.png`, { type: f.type }))
    setPendingFiles((p) => [...p, ...named].slice(0, 5))
    toast.success(named.length > 1 ? `Добавлено изображений: ${named.length}` : 'Скриншот добавлен — напишите подпись и отправьте')
  }
  // Перетаскивание файлов/картинок прямо в область чата
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const files = Array.from(e.dataTransfer?.files || [])
    if (files.length) setPendingFiles((p) => [...p, ...files].slice(0, 5))
  }
  const archiveRoom = async (id: string, on: boolean) => {
    try {
      await (on ? chat.archiveRoom(id) : chat.unarchiveRoom(id))
      qc.invalidateQueries({ queryKey: ['chat-rooms'] })
      toast.success(on ? 'Чат архивирован' : 'Чат возвращён')
      if (on && selectedRoom === id) setSelectedRoom(null)
    } catch { toast.error('Не удалось') }
  }
  const toggleRoomInFolder = (f: ChatFolderModel, roomId: string) => {
    const roomIds = f.roomIds.includes(roomId) ? f.roomIds.filter((x) => x !== roomId) : [...f.roomIds, roomId]
    chat.updateFolder(f.id, f.name, roomIds).then(() => qc.invalidateQueries({ queryKey: ['chat-folders'] })).catch(() => toast.error('Не удалось обновить папку'))
  }
  const deleteFolder = (id: string) => {
    chat.deleteFolder(id).then(() => { qc.invalidateQueries({ queryKey: ['chat-folders'] }); if (folder === id) setFolder('all') }).catch(() => toast.error('Не удалось удалить папку'))
  }
  const reorderFolders = (draggedId: string, targetId: string) => {
    const ids = folders.map((f) => f.id)
    const from = ids.indexOf(draggedId), to = ids.indexOf(targetId)
    if (from < 0 || to < 0 || from === to) return
    ids.splice(to, 0, ids.splice(from, 1)[0])
    chat.reorderFolders(ids).then(() => qc.invalidateQueries({ queryKey: ['chat-folders'] })).catch(() => {})
  }

  // ── производные ──
  const activeRoom = selectedRoom ? rooms.find((r) => r.id === selectedRoom) : undefined
  const isAdmin = user?.role === 'admin' || !!user?.is_superadmin
  const canWrite = activeRoom?.kind !== 'news' || NEWS_WRITER_ROLES.has(user?.role || '')
  const peerPresence = activeRoom?.type === 'direct' && activeRoom.directPeerId ? presenceMap.get(activeRoom.directPeerId) : undefined

  const filteredRooms = useMemo(() => {
    const custom = folders.find((f) => f.id === folder)
    const s = listSearch.trim().toLowerCase()
    const visible = rooms.filter((r) => {
      if (folder === 'group' && !(r.type === 'group' || r.type === 'company')) return false
      if (folder === 'direct' && r.type !== 'direct') return false
      if (custom && !custom.roomIds.includes(r.id)) return false
      return !s || (r.name || '').toLowerCase().includes(s) || (r.lastMessage || '').toLowerCase().includes(s)
    })
    const rank = (r: ChatRoom) => (r.kind === 'general' ? 0 : r.kind === 'news' ? 1 : 2)
    return [...visible].sort((a, b) => rank(a) - rank(b))
  }, [rooms, listSearch, folder, folders])

  const unreadByFolder = useMemo(() => {
    const acc: Record<string, number> = { all: 0, group: 0, direct: 0 }
    for (const f of folders) acc[f.id] = 0
    for (const r of rooms) {
      const n = r.unreadCount || 0
      acc.all += n
      if (r.type === 'group' || r.type === 'company') acc.group += n
      if (r.type === 'direct') acc.direct += n
      for (const f of folders) if (f.roomIds.includes(r.id)) acc[f.id] += n
    }
    return acc
  }, [rooms, folders])
  const totalUnread = useMemo(() => rooms.reduce((a, r) => a + (r.unreadCount || 0), 0), [rooms])

  const mentionCandidates = useMemo(() => {
    if (mentionQuery === null) return []
    const list = roomDetail?.participants || []
    const q = mentionQuery.toLowerCase()
    return list.filter((p) => p.userId !== user?.id && p.name).filter((p) => !q || p.name.toLowerCase().includes(q)).slice(0, 6)
  }, [mentionQuery, roomDetail, user?.id])
  const insertMention = (p: ChatParticipant) => {
    mentionMapRef.current.set(p.name, p.userId)
    setMessageText((prev) => prev.replace(/@([\wа-яА-ЯёЁ-]*)$/, `@${p.name} `))
    setMentionQuery(null)
  }

  const chatImages = useMemo(() => messages.filter(isImageMessage).map((m) => ({ path: m.fileUrl!, name: m.fileName || undefined })), [messages])
  const openImage = useCallback((path: string) => {
    setLightbox({ items: chatImages, index: Math.max(0, chatImages.findIndex((i) => i.path === path)) })
  }, [chatImages])

  // ── список комнат ──
  const listView = (
    <div className="flex h-full flex-col bg-card">
      <div className="shrink-0 border-b border-border/50 px-2.5 py-2">
        <div className="mb-2 flex items-center gap-2">
          <MessageCircle className="size-4 text-muted-foreground" />
          <span className="text-sm font-semibold">Чаты</span>
          {totalUnread > 0 && <span className="rounded-full bg-primary/15 px-1.5 text-[10px] text-primary">{totalUnread}</span>}
          <div className="flex-1" />
          <button onClick={() => setShowArchived((v) => !v)} title={showArchived ? 'Активные' : 'Архив'}
            className={cn('inline-flex size-7 items-center justify-center rounded-md transition-colors', showArchived ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
            <Archive className="size-4" />
          </button>
          <button onClick={() => setCreateOpen(true)} title="Новый чат"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <Plus className="size-4" />
          </button>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={listSearch} onChange={(e) => setListSearch(e.target.value)} placeholder="Поиск…" className="h-8 pl-8 text-xs" />
        </div>
        {/* Чипы папок (одноколоночный режим: мобильный / узкий док) */}
        {singleColumn && (
          <div className="mt-2 flex gap-1 overflow-x-auto pb-0.5">
            {FOLDERS.map((f) => (
              <button key={f.key} onClick={() => setFolder(f.key)}
                className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition-colors', folder === f.key ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground')}>
                <f.icon className="size-3" />{f.label}
                {unreadByFolder[f.key] > 0 && <span className="ml-0.5 rounded-full bg-primary px-1 text-[9px] text-primary-foreground">{unreadByFolder[f.key]}</span>}
              </button>
            ))}
            {folders.map((f) => (
              <button key={f.id} onClick={() => setFolder(f.id)}
                className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition-colors', folder === f.id ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground')}>
                <Folder className="size-3" />{f.name}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-1">
        {filteredRooms.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
            <MessageCircle className="size-6 opacity-20" />
            <span className="text-xs">Нет чатов</span>
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setCreateOpen(true)}><Plus className="mr-1 size-3" />Создать</Button>
          </div>
        ) : filteredRooms.map((room) => {
          const Icon = roomIcon(room)
          const isSystem = room.kind === 'news' || room.kind === 'general'
          const peerOnline = room.type === 'direct' && room.directPeerId ? presenceMap.get(room.directPeerId)?.online : false
          return (
            <div key={room.id} onClick={() => { setSelectedRoom(room.id); setShowRoomInfo(false) }}
              className={cn('group/room flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent',
                selectedRoom === room.id && 'bg-accent')}>
              <div className="relative">
                {isSystem ? (
                  <div className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground"><Icon className="size-5" /></div>
                ) : room.type === 'direct' ? (
                  <Avatar seed={room.id} name={room.name} online={!!peerOnline} size={40} />
                ) : (
                  <Avatar seed={room.id} name={room.name} icon={Icon} size={40} />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-1">
                  <span className="truncate text-sm font-medium">{room.name || 'Чат'}</span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <span className="text-[10px] text-muted-foreground">{fmtAge(room.lastMessageAt)}</span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button onClick={(e) => e.stopPropagation()} className="rounded p-0.5 opacity-0 transition-opacity hover:bg-muted group-hover/room:opacity-100 [@media(pointer:coarse)]:opacity-100">
                          <MoreVertical className="size-3.5 text-muted-foreground" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                        {!isSystem && (showArchived ? (
                          <DropdownMenuItem className="gap-2 text-xs" onClick={() => archiveRoom(room.id, false)}>
                            <ArchiveRestore className="size-3.5" />Вернуть из архива
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem className="gap-2 text-xs" onClick={() => archiveRoom(room.id, true)}>
                            <Archive className="size-3.5" />Архивировать
                          </DropdownMenuItem>
                        ))}
                        {folders.length > 0 && (
                          <>
                            <DropdownMenuSeparator />
                            {folders.map((f) => (
                              <DropdownMenuItem key={f.id} className="gap-2 text-xs" onClick={() => toggleRoomInFolder(f, room.id)}>
                                {f.roomIds.includes(room.id) ? <Check className="size-3.5 text-primary" /> : <Folder className="size-3.5" />}{f.name}
                              </DropdownMenuItem>
                            ))}
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                    {room.pinnedMessage && <Pin className="mr-1 inline size-3 text-blue-400" />}
                    {room.lastMessage || 'Нет сообщений'}
                  </p>
                  {(room.unreadCount ?? 0) > 0 && (
                    <span className="shrink-0 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">{room.unreadCount}</span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )

  // ── переписка ──
  const conversationView = !selectedRoom ? null : (
    <div className="flex h-full flex-col bg-background">
      {/* Шапка */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-border/50 px-3 py-2">
        <button className="inline-flex size-7 max-md:size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={() => { if (showRoomInfo) setShowRoomInfo(false); else setSelectedRoom(null) }}>
          <ChevronLeft className="size-4" />
        </button>
        <button onClick={() => setShowRoomInfo((v) => !v)} className="group/header flex min-w-0 flex-1 items-center gap-2.5 text-left">
          <div className="relative">
            {activeRoom?.kind === 'news' || activeRoom?.kind === 'general' ? (
              <div className="flex size-8 items-center justify-center rounded-full bg-muted text-muted-foreground">
                {activeRoom.kind === 'news' ? <Megaphone className="size-4" /> : <Building2 className="size-4" />}
              </div>
            ) : (
              <Avatar seed={activeRoom?.id || ''} name={activeRoom?.name} online={!!peerPresence?.online} size={32} />
            )}
          </div>
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold group-hover/header:text-primary">{activeRoom?.name || 'Чат'}</span>
            <span className={cn('block truncate text-[11px]', peerPresence?.online ? 'text-emerald-500' : 'text-muted-foreground')}>
              {peerPresence ? presenceText(peerPresence) : activeRoom?.participantCount ? `${activeRoom.participantCount} участн.` : ''}
            </span>
          </div>
        </button>
        {canWrite && (
          <button onClick={() => callMutation.mutate()} disabled={callMutation.isPending} title="Видеозвонок"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50">
            <Video className="size-4" />
          </button>
        )}
        <button onClick={() => { setShowMessageSearch((v) => !v); if (showMessageSearch) setMessageSearch('') }} title="Поиск"
          className={cn('inline-flex size-7 items-center justify-center rounded-md transition-colors', showMessageSearch ? 'bg-accent text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
          <SearchIcon className="size-4" />
        </button>
        <button onClick={() => setShowRoomInfo((v) => !v)} title="Участники"
          className={cn('inline-flex size-7 items-center justify-center rounded-md transition-colors', showRoomInfo ? 'bg-accent text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
          <UserPlus className="size-4" />
        </button>
      </div>

      {showMessageSearch && (
        <div className="shrink-0 border-b border-border/50 px-2.5 py-1.5">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-foreground" />
            <input autoFocus value={messageSearch} onChange={(e) => setMessageSearch(e.target.value)} placeholder="Поиск в сообщениях…"
              className="h-7 w-full rounded border border-border bg-muted/40 pl-7 pr-6 text-xs outline-none focus:ring-1 focus:ring-primary" />
            {messageSearch && <button onClick={() => setMessageSearch('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"><X className="size-3" /></button>}
          </div>
        </div>
      )}

      {showRoomInfo ? (
        <RoomInfoPanel room={activeRoom} participants={roomDetail?.participants} userId={user?.id}
          canManage={isAdmin || activeRoom?.createdBy === user?.id}
          onAdd={(uid) => { chat.addParticipant(selectedRoom!, uid).then(() => { qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success('Участник добавлен') }).catch(() => toast.error('Не удалось добавить')) }}
          onMessageUser={(uid) => openDirectMutation.mutate(uid)} presenceMap={presenceMap} />
      ) : (
        <>
          {/* Закреп */}
          {activeRoom?.pinnedMessage && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border/50 bg-muted/40 px-3 py-1.5">
              <Pin className="size-3 shrink-0 text-blue-400" />
              <div className="min-w-0 flex-1">
                <div className="text-[9px] font-medium text-blue-400">Закреплено · {activeRoom.pinnedMessage.userName || ''}</div>
                <div className="truncate text-[11px] text-muted-foreground">{activeRoom.pinnedMessage.content}</div>
              </div>
              <button onClick={() => pinMutation.mutate(null)} className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground" title="Открепить"><X className="size-3" /></button>
            </div>
          )}

          {/* Лента */}
          <div className="flex-1 overflow-y-auto">
            <div className="flex flex-col p-2.5">
              {(() => {
                const grouping = computeGrouping(messages)
                const items: { msg: ChatMessage; album?: ChatMessage[]; index: number }[] = []
                const skipped = new Set<number>()
                for (let i = 0; i < messages.length; i++) {
                  if (skipped.has(i)) continue
                  const m = messages[i]
                  if (isImageMessage(m)) {
                    const album = [m]
                    let j = i + 1
                    while (j < messages.length && isImageMessage(messages[j]) && messages[j].userId === m.userId && !messages[j].content
                      && new Date(messages[j].createdAt).getTime() - new Date(messages[j - 1].createdAt).getTime() < 120000) {
                      album.push(messages[j]); skipped.add(j); j++
                    }
                    items.push({ msg: m, album: album.length > 1 ? album : undefined, index: i })
                  } else items.push({ msg: m, index: i })
                }
                return items.map(({ msg, album, index }) => {
                  const isOwn = msg.userId === user?.id
                  return (
                    <ChatBubble key={msg.id} message={msg} album={album} isOwn={isOwn} grouping={grouping[index]}
                      canDelete={isOwn || isAdmin || activeRoom?.createdBy === user?.id}
                      editingId={editingId} editText={editText} searchHighlight={messageSearch}
                      onReply={() => setReplyTo(msg)}
                      onEditStart={() => { setEditingId(msg.id); setEditText(msg.content) }}
                      onEditCancel={() => { setEditingId(null); setEditText('') }}
                      onEditSave={() => editMutation.mutate({ id: msg.id, content: editText })}
                      onEditTextChange={setEditText}
                      onDelete={() => deleteMutation.mutate(msg.id)}
                      onAuthorClick={!isOwn && msg.userId && activeRoom?.type !== 'direct' ? () => openDirectMutation.mutate(msg.userId!) : undefined}
                      onReact={(emoji) => reactMutation.mutate({ id: msg.id, emoji })}
                      onPin={() => pinMutation.mutate(msg.id)}
                      onImageClick={openImage} />
                  )
                })
              })()}
              {messages.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">Пока нет сообщений. Напишите первым.</p>}
              <div ref={endRef} />
            </div>
          </div>

          {typingUsers.size > 0 && (
            <div className="shrink-0 px-3 py-0.5 text-[10px] italic text-muted-foreground">{Array.from(typingUsers.values()).join(', ')} печатает…</div>
          )}

          {replyTo && (
            <div className="flex shrink-0 items-center gap-2 border-t border-border/50 bg-muted/30 px-3 py-1.5">
              <div className="h-6 w-0.5 shrink-0 rounded-full bg-blue-500" />
              <div className="min-w-0 flex-1">
                <div className="text-[10px] font-medium text-blue-400">{replyTo.userName}</div>
                <div className="truncate text-[10px] text-muted-foreground">{replyTo.content || (replyTo.fileName ? `📎 ${replyTo.fileName}` : '')}</div>
              </div>
              <button onClick={() => setReplyTo(null)} className="shrink-0 text-muted-foreground hover:text-foreground"><X className="size-3" /></button>
            </div>
          )}

          {/* Композер */}
          {canWrite ? (
            <div
              className={cn('relative shrink-0 border-t border-border/50 p-2', dragOver && 'ring-2 ring-inset ring-primary/60 bg-primary/5')}
              onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true) }}
              onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false) }}
              onDrop={handleDrop}
            >
              {dragOver && (
                <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded bg-background/70 text-xs font-medium text-primary">
                  Отпустите — прикрепим к сообщению
                </div>
              )}
              {mentionCandidates.length > 0 && (
                <div className="absolute bottom-full left-2 z-20 mb-1 w-64 overflow-hidden rounded-lg border border-border bg-popover shadow-xl">
                  {mentionCandidates.map((p) => (
                    <button key={p.userId} onClick={() => insertMention(p)} className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-accent">
                      <Avatar seed={p.userId} name={p.name} size={24} />
                      <span className="min-w-0 flex-1 truncate text-xs">{p.name}</span>
                      <AtSign className="size-3 shrink-0 text-muted-foreground" />
                    </button>
                  ))}
                </div>
              )}
              {pendingFiles.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {pendingFiles.map((f, i) => (
                    <PendingThumb key={i} file={f} onRemove={() => setPendingFiles((p) => p.filter((_, k) => k !== i))} />
                  ))}
                </div>
              )}
              <div className="flex items-end gap-1.5">
                <input ref={fileInputRef} type="file" multiple hidden
                  onChange={(e) => { const fs = Array.from(e.target.files || []); setPendingFiles((p) => [...p, ...fs].slice(0, 5)); if (fileInputRef.current) fileInputRef.current.value = '' }} />
                <button onClick={() => fileInputRef.current?.click()} disabled={uploading || sendMutation.isPending}
                  className="inline-flex size-8 max-md:size-10 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50" title="Прикрепить файл">
                  <Paperclip className="size-4" />
                </button>
                {compact && !isMobile && (
                  <button onClick={() => setCapturing(true)} disabled={uploading || sendMutation.isPending}
                    className="inline-flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50" title="Снимок области экрана">
                    <Camera className="size-4" />
                  </button>
                )}
                <textarea value={messageText} onChange={(e) => handleTextChange(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                  onPaste={handlePaste}
                  placeholder="Сообщение… (Ctrl+V — вставить скриншот)" rows={1}
                  className="max-h-[80px] min-h-[32px] flex-1 resize-none rounded-2xl border border-border bg-muted/40 px-3 py-1.5 text-xs outline-none focus:ring-1 focus:ring-primary" />
                <button onClick={handleSend} disabled={(!messageText.trim() && !pendingFiles.length) || sendMutation.isPending || uploading}
                  className="inline-flex size-8 max-md:size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50" title="Отправить">
                  {uploading || sendMutation.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex shrink-0 items-center gap-2 border-t border-border/50 px-3 py-2 text-[11px] text-muted-foreground">
              <Lock className="size-3.5 shrink-0" />Канал объявлений: публикуют администраторы
            </div>
          )}
        </>
      )}
      {lightbox && (
        <Lightbox items={lightbox.items} index={lightbox.index} onClose={() => setLightbox(null)}
          onNavigate={(d) => setLightbox((lb) => lb && ({ ...lb, index: Math.min(Math.max(lb.index + d, 0), lb.items.length - 1) }))} />
      )}
      {capturing && (
        <RegionCapture onCancel={() => setCapturing(false)}
          onCapture={(f) => { setPendingFiles((p) => [...p, f].slice(0, 5)); setCapturing(false); toast.success('Область захвачена — напишите подпись и отправьте') }} />
      )}
    </div>
  )

  // Диалоги (общие для обоих режимов)
  const dialogs = (
    <>
      <CreateChatDialog open={createOpen} onOpenChange={setCreateOpen}
        onCreated={(id) => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); setSelectedRoom(id); setShowRoomInfo(false) }} />
      <Dialog open={folderDialogOpen} onOpenChange={setFolderDialogOpen}>
        <DialogContent className="max-w-xs gap-3 sm:max-w-xs">
          <DialogHeader><DialogTitle className="text-sm">Новая папка чатов</DialogTitle></DialogHeader>
          <Input autoFocus value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && newFolderName.trim()) createFolderMutation.mutate(newFolderName.trim()) }}
            placeholder="Название папки…" className="h-8 text-xs" />
          <p className="text-[11px] text-muted-foreground">Чаты добавляются в папку через меню «⋮» у чата в списке.</p>
          <Button onClick={() => createFolderMutation.mutate(newFolderName.trim())} disabled={!newFolderName.trim() || createFolderMutation.isPending} className="h-8 w-full text-xs">Создать</Button>
        </DialogContent>
      </Dialog>
    </>
  )

  // ── компоновка ──
  if (singleColumn) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        {selectedRoom ? conversationView : listView}
        {dialogs}
      </div>
    )
  }

  // Десктоп: рейл папок + список + переписка
  return (
    <div className="flex h-full min-h-0">
      {/* Рейл папок */}
      <div className="flex w-16 shrink-0 flex-col items-center gap-1 overflow-y-auto border-r border-border/50 bg-muted/30 py-2">
        {FOLDERS.map((f) => (
          <button key={f.key} onClick={() => setFolder(f.key)}
            className={cn('relative flex w-14 flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] transition-colors',
              folder === f.key ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
            <f.icon className="size-4" />{f.label}
            {unreadByFolder[f.key] > 0 && <span className="absolute right-1.5 top-1 min-w-[16px] rounded-full bg-primary px-1 text-[9px] leading-4 text-primary-foreground">{unreadByFolder[f.key]}</span>}
          </button>
        ))}
        {folders.length > 0 && <div className="my-1 h-px w-10 bg-border" />}
        {folders.map((f) => (
          <button key={f.id} onClick={() => setFolder(f.id)} draggable
            onDragStart={() => { dragFolderRef.current = f.id }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (dragFolderRef.current) reorderFolders(dragFolderRef.current, f.id); dragFolderRef.current = null }}
            title={`${f.name} · ${f.roomIds.length} чат(ов)`}
            className={cn('group/folder relative flex w-14 cursor-grab flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] transition-colors active:cursor-grabbing',
              folder === f.id ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
            <Folder className="size-4" />
            <span className="w-full truncate text-center">{f.name}</span>
            {(unreadByFolder[f.id] || 0) > 0 && <span className="absolute right-1.5 top-1 min-w-[16px] rounded-full bg-primary px-1 text-[9px] leading-4 text-primary-foreground">{unreadByFolder[f.id]}</span>}
            <span role="button" onClick={(e) => { e.stopPropagation(); deleteFolder(f.id) }}
              className="absolute left-0.5 top-0.5 hidden rounded bg-background p-0.5 text-muted-foreground hover:text-red-500 group-hover/folder:block" title="Удалить папку">
              <X className="size-2.5" />
            </span>
          </button>
        ))}
        <button onClick={() => setFolderDialogOpen(true)}
          className="flex w-14 flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
          <Plus className="size-4" />Папка
        </button>
      </div>
      {/* Список */}
      <div className="flex w-72 shrink-0 flex-col border-r border-border/50">{listView}</div>
      {/* Переписка */}
      <div className="flex min-w-0 flex-1 flex-col">
        {conversationView || (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
            <MessageCircle className="size-8 opacity-20" />
            <span className="text-xs">Выберите чат слева или создайте новый</span>
          </div>
        )}
      </div>
      {dialogs}
    </div>
  )
}

export default ChatPanel
