/**
 * Внутренний чат — полный порт мессенджера Coordinator (TSupport) под стек Ledger.
 * Telegram-механика: единый список комнат, папки-группировки (Все/Группы/Личные +
 * кастомные), закреплённые сообщения, реакции, ответы, @упоминания, редактирование/
 * удаление, медиа-альбомы + Lightbox, архив, видеозвонок. REST — chatService,
 * live — useChatWs. Рендерится в InteractionHost (модалка «Взаимодействие»).
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  MessageCircle, Send, Search, User as UserIcon, Building2, Users, Plus,
  ChevronLeft, ChevronRight, FileText, MoreVertical, Archive, ArchiveRestore,
  Trash2, Reply, Pencil, X, Check, Megaphone, Lock, Pin, Video, UserPlus,
  Folder, AtSign, Loader2, Paperclip, Camera, Search as SearchIcon,
  Shield, ShieldOff, UserMinus, LogOut, Bell, BellOff, Forward, MapPin, ClipboardList,
  Mail, Palette, Smile, Images, Volume2, VolumeX,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { SPACE_PRODUCTS } from '@/config/spaceProducts'
import { PartyBadge } from '@/components/chat/PartyBadge'
import { useIsMobile } from '@/hooks/use-mobile'
import { useChatWs, type WsEvent } from '@/hooks/useChatWs'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
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
import { AuthImage, AuthVideo, AuthFileChip, useAuthBlobUrl, downloadAttachment } from './AuthMedia'
import { RegionCapture } from './RegionCapture'
import { ensurePushSubscription, pushSupported, requestPushPermission } from '@/lib/chatPush'
import * as chat from '@/services/chatService'
import { isMuted } from '@/services/chatService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { useSupportContext } from '@/contexts/SupportContext'
import type {
  ChatRoom, ChatMessage, ChatParticipant, ChatPresence, ChatFolder as ChatFolderModel,
} from '@/services/chatService'

// ── константы ────────────────────────────────────────────────────────────────
const QUICK_REACTIONS = ['👍', '❤️', '🔥', '😂', '😮', '👏']
const NEWS_WRITER_ROLES = new Set(['admin', 'partner', 'coordinator', 'company', 'tech'])
/**
 * Разделы списка — как в Telegram: канал, группа и личный чат это разные сущности,
 * а не «чат с разными настройками». Канал односторонний (новости, рассылка, слово
 * руководителя), в группе говорят все, личный — про двоих.
 */
type FolderKey = 'all' | 'channel' | 'group' | 'direct'
const FOLDERS: { key: FolderKey; label: string; icon: typeof UserIcon }[] = [
  { key: 'all', label: 'Все', icon: MessageCircle },
  { key: 'channel', label: 'Каналы', icon: Megaphone },
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
  if (r.type === 'channel' || r.kind === 'news') return Megaphone
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
/**
 * Эмодзи для сообщения. Набор свой, а не библиотека: emoji-mart тянет мегабайт
 * данных и свой рендер ради панели, которой пользуются раз в день. Здесь —
 * ходовые символы по темам, этого хватает для рабочей переписки.
 */
const EMOJI_GROUPS: { name: string; items: string }[] = [
  { name: 'Часто', items: '👍👌✅❌🔥💪🙏👏🤝😀😁😂🤣🙂😉😊😍🤔🤷‍♂️🤦‍♂️' },
  { name: 'Лица', items: '😃😄😅😆😋😎🥳🤩😐😑😕😟😢😭😤😠🤬😱😴🤒🤕🥱🤗🤨' },
  { name: 'Жесты', items: '👋🤚✋👊✊🤛🤜👈👉👆👇☝️✌️🤞🤟🤙💅👐🙌🤲' },
  { name: 'Работа', items: '📌📍📎🗂️📁📄📃📊📈📉🗒️📝✏️🔧🔨⚙️🛠️🧰🔑🔒⏰📅✔️❗❓' },
  { name: 'Связь', items: '📞☎️📱💬💡📣📢🔔🔕📧✉️📬🌐🛰️🖥️💻⌨️🖱️🔌🔋' },
  { name: 'Место', items: '🏢🏭🚧🚗🚚🛻⛽🔥💧⚡🌡️🌦️❄️🌙☀️🧯🚨🅿️🛞🧭' },
  { name: 'Символы', items: '⭐🌟💯⚠️🚫♻️🔴🟠🟡🟢🔵🟣⚫⚪🔺🔻▶️⏸️⏹️🔄' },
]

/**
 * Карточка ссылки под сообщением: о чём страница, без открывания вкладки.
 * Тянется по требованию и кешируется react-query — одну и ту же ссылку в чате
 * разворачивают многие, повторно ходить на сервер незачем.
 */
function LinkCard({ url, mine }: { url: string; mine: boolean }) {
  const { data } = useQuery({
    queryKey: ['link-preview', url],
    queryFn: () => chat.getLinkPreview(url),
    staleTime: 60 * 60 * 1000,
    retry: false,
  })
  if (!data?.title && !data?.description) return null
  return (
    <a href={url} target="_blank" rel="noreferrer noopener"
      className={cn('mt-1 block rounded-md border-l-2 py-1 pl-2 pr-1.5 no-underline',
        mine ? 'border-white/70 bg-white/10' : 'border-primary bg-primary/5')}>
      {data.site && (
        <div className={cn('text-[10px]', mine ? 'text-primary-foreground/70' : 'text-muted-foreground')}>
          {data.site}
        </div>
      )}
      {data.title && <div className="text-[11px] font-semibold leading-snug">{data.title}</div>}
      {data.description && (
        <div className={cn('line-clamp-2 text-[11px] leading-snug',
          mine ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
          {data.description}
        </div>
      )}
    </a>
  )
}

/** Вложения чата одним экраном: фотографии сеткой, файлы списком. */
function RoomMediaDialog({ roomId, onClose, onImageClick }: {
  roomId: string; onClose: () => void; onImageClick: (path: string) => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['chat-room-media', roomId],
    queryFn: () => chat.getRoomMedia(roomId),
  })
  const items = data || []
  const images = items.filter((i) => i.type === 'image' || /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(i.fileName || i.fileUrl))
  const files = items.filter((i) => !images.includes(i))
  const [tab, setTab] = useState<'images' | 'files'>('images')
  const list = tab === 'images' ? images : files

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg gap-0 p-0">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Вложения чата</DialogTitle>
        </DialogHeader>
        <div className="flex gap-1 border-b border-border/50 px-4 py-2">
          {(['images', 'files'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={cn('rounded-md px-2 py-1 text-xs',
                tab === t ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground')}>
              {t === 'images' ? `Фото (${images.length})` : `Файлы (${files.length})`}
            </button>
          ))}
        </div>
        <div className="max-h-[60vh] overflow-y-auto p-3">
          {isLoading && <div className="text-xs text-muted-foreground">Загрузка…</div>}
          {!isLoading && list.length === 0 && (
            <div className="py-6 text-center text-xs text-muted-foreground">
              {tab === 'images' ? 'Фотографий пока нет' : 'Файлов пока нет'}
            </div>
          )}
          {tab === 'images' ? (
            <div className="grid grid-cols-3 gap-1.5">
              {images.map((i) => (
                <button key={i.messageId} onClick={() => { onImageClick(i.fileUrl); onClose() }}
                  className="aspect-square overflow-hidden rounded-md">
                  <AuthImage path={i.fileUrl} alt={i.fileName || ''} className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          ) : (
            <div className="space-y-1">
              {files.map((i) => (
                <div key={i.messageId} className="flex items-center gap-2 rounded-md px-1.5 py-1.5 hover:bg-accent">
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs">{i.fileName || 'файл'}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {i.userName || ''} · {fmtAge(i.createdAt)}
                      {i.fileSize ? ` · ${Math.max(1, Math.round(i.fileSize / 1024))} КБ` : ''}
                    </div>
                  </div>
                  <button type="button" title="Скачать"
                    onClick={() => downloadAttachment(i.fileUrl, i.fileName || undefined)}
                    className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground">
                    <FileText className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function EmojiPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [group, setGroup] = useState(0)
  return (
    <div className="w-[268px] p-1.5">
      <div className="mb-1 flex gap-0.5 overflow-x-auto">
        {EMOJI_GROUPS.map((g, i) => (
          <button key={g.name} onClick={() => setGroup(i)}
            className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px]',
              group === i ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground')}>
            {g.name}
          </button>
        ))}
      </div>
      <div className="grid max-h-[176px] grid-cols-8 gap-0.5 overflow-y-auto">
        {[...EMOJI_GROUPS[group].items].reduce<string[]>((acc, ch) => {
          // Составные эмодзи (жест + модификатор) — это несколько кодовых точек,
          // и посимвольный разбор рвал бы их пополам.
          const last = acc[acc.length - 1]
          if (last && /[‍️\u{1F3FB}-\u{1F3FF}]/u.test(ch)) acc[acc.length - 1] = last + ch
          else if (last && /[‍]$/u.test(last)) acc[acc.length - 1] = last + ch
          else acc.push(ch)
          return acc
        }, []).map((e, i) => (
          <button key={`${e}-${i}`} onClick={() => onPick(e)} title={e}
            className="flex size-8 items-center justify-center rounded text-[19px] leading-none hover:bg-accent">
            {e}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * Фон ленты — личная настройка человека, не свойство комнаты: для остальных
 * участников он ничего не значит, поэтому хранится в браузере. Узоры собраны
 * из CSS-градиентов, а не из картинок: лишних файлов в сборке не появляется,
 * и в тёмной теме фон остаётся приглушённым (полупрозрачные цвета поверх фона).
 */
const CHAT_SKINS: Record<string, { label: string; style?: React.CSSProperties }> = {
  none: { label: 'Обычный' },
  paper: {
    label: 'Бумага',
    style: {
      backgroundImage:
        'radial-gradient(circle at 1px 1px, color-mix(in srgb, currentColor 8%, transparent) 1px, transparent 0)',
      backgroundSize: '18px 18px',
    },
  },
  grid: {
    label: 'Клетка',
    style: {
      backgroundImage:
        'linear-gradient(color-mix(in srgb, currentColor 6%, transparent) 1px, transparent 1px),' +
        'linear-gradient(90deg, color-mix(in srgb, currentColor 6%, transparent) 1px, transparent 1px)',
      backgroundSize: '22px 22px',
    },
  },
  warm: {
    label: 'Тёплый',
    style: { backgroundImage: 'linear-gradient(160deg, rgba(245,158,11,0.10), transparent 55%)' },
  },
  cool: {
    label: 'Холодный',
    style: { backgroundImage: 'linear-gradient(160deg, rgba(56,189,248,0.12), transparent 55%)' },
  },
}

function Avatar({ seed, name, icon: Icon, online, size = 40, src }: {
  seed: string; name?: string | null; icon?: typeof UserIcon; online?: boolean; size?: number
  /** Фото человека или чата (/api/files/<id>); нет — генеративный кружок с инициалами. */
  src?: string | null
}) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      {src ? (
        <AuthImage path={src} alt={name || ''} className="h-full w-full rounded-full object-cover" />
      ) : (
        <div className={cn('flex h-full w-full items-center justify-center rounded-full font-semibold text-white', avatarColor(seed))}
          style={{ fontSize: size * 0.4 }}>
          {Icon ? <Icon style={{ width: size * 0.5, height: size * 0.5 }} /> : initials(name)}
        </div>
      )}
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

/** Позвать в чат по адресу: собеседник останется в своей почте. */
function MailInvite({ roomId, onAdded }: { roomId: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const invite = async () => {
    const addr = email.trim().toLowerCase()
    if (!addr.includes('@')) { toast.error('Нужен адрес электронной почты'); return }
    setBusy(true)
    try {
      await chat.addMailParticipant(roomId, addr, name.trim() || undefined)
      toast.success(`${addr} — участник чата, сообщения будут уходить письмом`)
      setEmail(''); setName(''); setOpen(false); onAdded()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось позвать по почте')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="mt-2 inline-flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground">
        <Mail className="size-3.5" /> Позвать по почте
      </button>
    )
  }
  return (
    <div className="mt-2 space-y-1.5 rounded-md border border-border p-2">
      <div className="text-[11px] text-muted-foreground">
        Человек останется в своей почте: сообщения этого чата придут ему письмом, а его
        ответ появится здесь. Вход в пространство ему не нужен.
      </div>
      <Input value={email} onChange={(e) => setEmail(e.target.value)}
        placeholder="адрес@компания.ру" className="h-8 text-xs" />
      <Input value={name} onChange={(e) => setName(e.target.value)}
        placeholder="Имя (необязательно)" className="h-8 text-xs" />
      <div className="flex items-center gap-1.5">
        <Button size="sm" className="h-7 text-xs" onClick={invite} disabled={busy}>
          {busy ? 'Добавляю…' : 'Позвать'}
        </Button>
        <Button size="sm" variant="ghost" className="h-7 text-xs"
          onClick={() => { setOpen(false); setEmail(''); setName('') }}>Отмена</Button>
      </div>
    </div>
  )
}

// ── панель информации о комнате (участники) ──────────────────────────────────
function RoomInfoPanel({
  room, participants, userId, canManage, canOwn, onAdd, onMailAdded, onRename, onAvatar,
  onScope, onObject, onRemove, onSetRole, onLeave, onMessageUser, onShowProfile, presenceMap,
}: {
  room?: ChatRoom
  participants?: ChatParticipant[]
  userId?: string
  /** Ведение чата: владелец или админ чата (добавить/убрать участника, имя). */
  canManage: boolean
  /** Права владельца: раздача ролей и снятие админов. */
  canOwn: boolean
  onAdd: (uid: string) => void
  /** Позвали участника по почте — перечитать состав комнаты. */
  onMailAdded: () => void
  onRename: (name: string) => void
  /** Файл нового аватара; null — убрать аватар. */
  onAvatar: (file: File | null) => void
  /** Смена привязки к приложению; '' — отвязать (чат всего пространства). */
  onScope: (code: string) => void
  /** Смена привязки к объекту; '' — отвязать. */
  onObject: (objectId: string) => void
  onRemove: (uid: string) => void
  onSetRole: (uid: string, role: 'admin' | 'member') => void
  onLeave: () => void
  onMessageUser: (uid: string) => void
  onShowProfile: (uid: string) => void
  presenceMap: Map<string, ChatPresence>
}) {
  const { companyId } = useCompany()
  const [q, setQ] = useState('')
  // Переименование — инлайн у заголовка: отдельного «меню чата» в панели нет.
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  // Поиск объекта для привязки: объектов сотни, селектом их не выбрать.
  const [objQ, setObjQ] = useState('')
  const { data: objHits = [] } = useQuery({
    queryKey: ['space-objects-pick', companyId, objQ],
    queryFn: () => listSpaceObjects(companyId!, objQ),
    enabled: !!companyId && objQ.trim().length >= 2,
  })
  // Состав системных чатов ведёт пространство, у личной переписки имени нет.
  const editable = canManage && !room?.kind && room?.type !== 'direct'
  // Аватар шире имени: у системного чата имя закрыто, а картинку владелец менять может.
  const avatarEditable = canManage && room?.type !== 'direct'
  const { data: found = [] } = useQuery({
    queryKey: ['chat-user-search', companyId, q],
    queryFn: () => chat.searchUsers(q),
    enabled: canManage,
  })
  const memberIds = new Set((participants || []).map((p) => p.userId))
  const addable = found.filter((u) => !memberIds.has(u.userId))
  const owner = (participants || []).find((p) => p.role === 'owner')
  const peer = room?.type === 'direct'
    ? (participants || []).find((p) => p.userId !== userId) : undefined
  const external = (participants || []).filter((p) => p.isExternal)
  // Что это за чат и почему он здесь: вид, кто ведёт, к какому приложению привязан.
  // Без этой карточки панель отвечала только «кто внутри», а вопрос «что это такое»
  // оставался открытым — особенно у групп, которые пространство завело само.
  const kindText = room?.kind === 'platform' ? 'Канал разработчика платформы'
    : room?.kind === 'news' ? 'Канал компании — пишут владелец и администраторы'
    : room?.kind === 'general' ? 'Общая группа пространства'
    // Группа приложения опознаётся по scopeProduct (ниже), а не по kind:
    // прежней метки `app:<код>` бэкенд не ставит.
    : room?.scopeProduct ? 'Группа приложения'
    : room?.type === 'channel' ? 'Канал — односторонний: пишут владелец и админы'
    : room?.type === 'group' ? 'Группа — пишут все участники'
    : room?.type === 'direct' ? 'Личная переписка' : 'Чат пространства'
  const scopeLabel = room?.scopeProduct
    ? SPACE_PRODUCTS.find((s) => s.code === room.scopeProduct)?.label || room.scopeProduct
    : null
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3">
      <div className="mb-3 rounded-lg border border-border/70 bg-muted/25 p-2.5">
        <div className="mb-2 flex items-center gap-2.5">
          {room?.avatarUrl ? (
            <AuthImage path={room.avatarUrl} alt={room?.name || 'Чат'}
              className="size-10 shrink-0 rounded-full object-cover" />
          ) : (
            <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
              {(() => { const I = roomIcon(room ?? { type: 'group' }); return <I className="size-5" /> })()}
            </div>
          )}
          {avatarEditable && (
            <div className="flex items-center gap-2 text-[11px]">
              <label className="cursor-pointer text-primary hover:underline">
                {room?.avatarUrl ? 'Сменить аватар' : 'Загрузить аватар'}
                <input type="file" accept="image/*" className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) onAvatar(f); e.target.value = '' }} />
              </label>
              {room?.avatarUrl && (
                <button type="button" onClick={() => onAvatar(null)}
                  className="text-muted-foreground hover:text-destructive">Убрать</button>
              )}
            </div>
          )}
        </div>
        {nameDraft !== null ? (
          <div className="flex items-center gap-1">
            <Input autoFocus value={nameDraft} onChange={(e) => setNameDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && nameDraft.trim()) { onRename(nameDraft.trim()); setNameDraft(null) }
                if (e.key === 'Escape') setNameDraft(null)
              }}
              className="h-7 text-[13px]" placeholder="Название чата" />
            <button onClick={() => { if (nameDraft.trim()) { onRename(nameDraft.trim()); setNameDraft(null) } }}
              className="rounded p-1 text-primary hover:bg-accent" title="Сохранить">
              <Check className="size-4" />
            </button>
            <button onClick={() => setNameDraft(null)}
              className="rounded p-1 text-muted-foreground hover:text-foreground" title="Отмена">
              <X className="size-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <div className="min-w-0 truncate text-[13px] font-medium">{room?.name || peer?.name || 'Чат'}</div>
            {editable && (
              <button onClick={() => setNameDraft(room?.name || '')}
                className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
                title="Переименовать чат">
                <Pencil className="size-3.5" />
              </button>
            )}
          </div>
        )}
        <div className="mt-0.5 text-[11px] text-muted-foreground">{kindText}</div>
        <dl className="mt-2 space-y-1 text-[11px]">
          {peer ? (
            <>
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">Собеседник</dt>
                <dd className="min-w-0 truncate">{peer.name}</dd>
              </div>
              {peer.companyName && (
                <div className="flex gap-2">
                  <dt className="w-24 shrink-0 text-muted-foreground">Компания</dt>
                  <dd className="min-w-0 truncate">{peer.companyName}</dd>
                </div>
              )}
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">Сейчас</dt>
                <dd>{presenceMap.get(peer.userId)?.online || peer.online ? 'в сети' : 'не в сети'}</dd>
              </div>
            </>
          ) : (
            <>
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">Ведёт</dt>
                <dd className="min-w-0 truncate">{owner?.name || 'не назначен'}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">Участников</dt>
                <dd className="tabular-nums">
                  {participants?.length ?? 0}
                  {external.length > 0 && (
                    <span className="ml-1 text-amber-600 dark:text-amber-400"
                      title={external.map((p) => `${p.name}${p.companyName ? ` · ${p.companyName}` : ''}`).join(', ')}>
                      +{external.length} от партнёров
                    </span>
                  )}
                </dd>
              </div>
            </>
          )}
          <div className="flex items-center gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">Приложение</dt>
            {/* Владелец меняет привязку на месте: «специализированная группа» — это
                настройка самой группы, а не привилегия админа пространства. */}
            {editable ? (
              <dd className="min-w-0 flex-1">
                <Select value={room?.scopeProduct || 'none'}
                  onValueChange={(v) => onScope(v === 'none' ? '' : v)}>
                  <SelectTrigger className="h-6 w-full max-w-[180px] px-2 text-[11px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Всё пространство</SelectItem>
                    {SPACE_PRODUCTS.map((p) => (
                      <SelectItem key={p.code} value={p.code}>{p.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </dd>
            ) : (
              <dd className="min-w-0 truncate">{scopeLabel || 'всё пространство'}</dd>
            )}
          </div>
          {/* Объект: группа «по станции» видна из карточки этого объекта, и наоборот —
              карточка показывает свои обсуждения. Привязку ведёт владелец чата. */}
          {room?.type !== 'direct' && !room?.kind && (
            <div className="flex items-start gap-2">
              <dt className="w-24 shrink-0 pt-0.5 text-muted-foreground">Объект</dt>
              <dd className="min-w-0 flex-1">
                {room?.scopeObjectId ? (
                  <span className="flex items-center gap-1">
                    <span className="min-w-0 truncate">{room.scopeObjectName || room.scopeObjectId}</span>
                    {editable && (
                      <button type="button" onClick={() => onObject('')}
                        className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive"
                        title="Отвязать от объекта">
                        <X className="size-3" />
                      </button>
                    )}
                  </span>
                ) : editable ? (
                  <div className="relative">
                    <Input value={objQ} onChange={(e) => setObjQ(e.target.value)}
                      placeholder="Найти объект…" className="h-6 px-2 text-[11px]" />
                    {objQ.trim().length >= 2 && objHits.length > 0 && (
                      <div className="absolute z-20 mt-1 max-h-40 w-full overflow-y-auto rounded-md border border-border bg-popover p-0.5 shadow-md">
                        {objHits.slice(0, 8).map((o) => (
                          <button key={o.id} type="button"
                            onClick={() => { onObject(o.id); setObjQ('') }}
                            className="block w-full truncate rounded px-1.5 py-1 text-left text-[11px] hover:bg-accent">
                            {o.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <span className="text-muted-foreground">не привязан</span>
                )}
              </dd>
            </div>
          )}
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">Моя роль</dt>
            <dd>{room?.myRole === 'owner' ? 'владелец' : room?.myRole === 'admin' ? 'админ' : 'участник'}</dd>
          </div>
        </dl>
      </div>
      <div className="mb-3">
        <div className="mb-1 text-xs font-semibold text-muted-foreground">Участники · {participants?.length ?? 0}</div>
        <div className="space-y-0.5">
          {(participants || []).map((p) => {
            const online = presenceMap.get(p.userId)?.online || p.online
            return (
              <div key={p.userId} className="flex items-center gap-2.5 rounded-md px-1.5 py-1.5 hover:bg-accent">
                {/* Клик по человеку — карточка «кто это»: должность, компания, входы. */}
                <button type="button" onClick={() => onShowProfile(p.userId)}
                  className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                  title="Кто это — карточка человека">
                <Avatar seed={p.userId} name={p.name} online={online} size={32} src={p.avatarUrl} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[13px]">{p.name}{p.userId === userId && ' (вы)'}</span>
                    {/* Чей это человек — первое, что нужно знать перед тем, как писать:
                        в смешанной группе рядом сидят инженер платформы, свой сотрудник
                        и человек партнёра. Один и тот же бейдж во всех разрезах. */}
                    <PartyBadge party={{
                      partyType: p.partyType ?? (p.isExternal ? 'partner' : 'internal'),
                      role: p.role === 'owner' || p.role === 'admin' ? 'admin' : undefined,
                      orgName: p.companyName,
                    }} />
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {p.mailOnly
                      ? `по почте · ${p.email ?? ''}`
                      : p.role === 'owner' ? 'владелец' : p.role === 'admin' ? 'админ' : 'участник'}
                    {p.isExternal && p.companyName ? ` · ${p.companyName}` : ''}
                  </div>
                </div>
                </button>
                {p.userId !== userId && room?.type !== 'direct' && (
                  <button onClick={() => onMessageUser(p.userId)} className="rounded p-1 text-muted-foreground hover:text-foreground" title="Написать лично">
                    <MessageCircle className="size-4" />
                  </button>
                )}
                {/* Опасные действия (роль, убрать) — не в общем ряду иконок, а за «⋮»:
                    случайный клик по ряду не должен выкидывать человека из чата. */}
                {editable && p.userId !== userId && p.role !== 'owner'
                  && (canOwn || p.role === 'member') && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className="rounded p-1 text-muted-foreground hover:text-foreground"
                        title="Управление участником">
                        <MoreVertical className="size-4" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="text-[13px]">
                      {canOwn && (
                        p.role === 'admin' ? (
                          <DropdownMenuItem onClick={() => onSetRole(p.userId, 'member')}>
                            <ShieldOff className="mr-2 size-4" /> Снять админа чата
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem onClick={() => onSetRole(p.userId, 'admin')}>
                            <Shield className="mr-2 size-4" /> Сделать админом чата
                          </DropdownMenuItem>
                        )
                      )}
                      {canOwn && <DropdownMenuSeparator />}
                      <DropdownMenuItem onClick={() => onRemove(p.userId)}
                        className="text-destructive focus:text-destructive">
                        <UserMinus className="mr-2 size-4" /> Убрать из чата
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
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
                <Avatar seed={u.userId} name={u.name} online={u.online} size={30} src={u.avatarUrl} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{u.name}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{u.email}</div>
                </div>
                <Plus className="size-4 shrink-0 text-primary" />
              </button>
            ))}
          </div>
          {/* Собеседник может вообще не заходить в пространство — подрядчик,
              поставщик, инженер заказчика. Его зовут по адресу, и разговор для
              него выглядит перепиской в собственной почте. */}
          <MailInvite roomId={room!.id} onAdded={onMailAdded} />
        </div>
      )}
      {/* Выход — только из обычных групп: системные чаты и каналы обязательны,
          владелец сначала передаёт группу. */}
      {room?.type === 'group' && !room?.kind && room?.myRole !== 'owner' && (
        <button onClick={onLeave}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[12px] text-muted-foreground hover:text-destructive">
          <LogOut className="size-3.5" /> Выйти из группы
        </button>
      )}
    </div>
  )
}

// ── глобальный поиск по сообщениям всех чатов ────────────────────────────────
function GlobalSearchResults({ q, onOpen }: {
  q: string
  onOpen: (roomId: string, messageId: string) => void
}) {
  const { data: hits = [], isLoading } = useQuery({
    queryKey: ['chat-global-search', q],
    queryFn: () => chat.searchAllMessages(q),
    enabled: q.trim().length >= 3,
  })
  if (q.trim().length < 3) return null
  return (
    <div className="border-t border-border/50 px-1 pt-2">
      <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Сообщения
      </div>
      {isLoading && (
        <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Ищем…
        </div>
      )}
      {!isLoading && hits.length === 0 && (
        <p className="px-2 py-2 text-xs text-muted-foreground">Ничего не найдено</p>
      )}
      {hits.map((h) => (
        <button key={h.messageId} type="button" onClick={() => onOpen(h.roomId, h.messageId)}
          className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-accent">
          <span className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate text-xs font-medium">{h.roomName}</span>
            <span className="shrink-0 text-[10px] text-muted-foreground">{fmtAge(h.createdAt)}</span>
          </span>
          <span className="block truncate text-[11px] text-muted-foreground">
            {h.userName ? `${h.userName}: ` : ''}{h.preview}
          </span>
        </button>
      ))}
    </div>
  )
}

// ── «В заявку»: обсудили — отправили на выполнение ───────────────────────────
function TicketFromMessageDialog({ message, defaultObjectId, defaultObjectName, onClose, onDone }: {
  message: ChatMessage
  defaultObjectId: string | null
  defaultObjectName: string | null
  onClose: () => void
  onDone: (ticketNumber: string | null) => void
}) {
  const { companyId } = useCompany()
  const [title, setTitle] = useState((message.content || message.fileName || '').slice(0, 90))
  const [priority, setPriority] = useState<'low' | 'medium' | 'high'>('medium')
  // Объект обязателен: заявка в Поддержке живёт при объекте (эко-канал).
  const [objectId, setObjectId] = useState<string | null>(defaultObjectId)
  const [objectName, setObjectName] = useState<string | null>(defaultObjectName)
  const [objQ, setObjQ] = useState('')
  const [busy, setBusy] = useState(false)
  const { data: objHits = [] } = useQuery({
    queryKey: ['space-objects-pick', companyId, objQ],
    queryFn: () => listSpaceObjects(companyId!, objQ),
    enabled: !!companyId && !objectId && objQ.trim().length >= 2,
  })
  const send = async () => {
    setBusy(true)
    try {
      const res = await chat.ticketFromMessage(message.id,
        { objectId: objectId || undefined, title: title.trim() || undefined, priority })
      onDone(res.ticketNumber)
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось создать заявку')
    } finally { setBusy(false) }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-sm gap-0 p-0 sm:max-w-sm">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Заявка из сообщения</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 p-4">
          <p className="max-h-20 overflow-hidden rounded-md bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
            {message.userName ? `${message.userName}: ` : ''}{message.content || message.fileName || 'вложение'}
          </p>
          <div className="space-y-1">
            <label className="text-xs font-medium">Заголовок</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="Что нужно сделать" className="h-8 text-sm" />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium">Объект</label>
            {objectId ? (
              <div className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-sm">
                <MapPin className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{objectName || objectId}</span>
                <button type="button" onClick={() => { setObjectId(null); setObjectName(null) }}
                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground" title="Выбрать другой">
                  <X className="size-3.5" />
                </button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-1.5 rounded-md border border-dashed border-border px-2.5 py-1.5 text-sm text-muted-foreground">
                  <MapPin className="size-3.5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">Офис — по умолчанию</span>
                </div>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input value={objQ} onChange={(e) => setObjQ(e.target.value)}
                    placeholder="Или укажите станцию…" className="h-8 pl-8 text-sm" />
                  {objQ.trim().length >= 2 && objHits.length > 0 && (
                    <div className="absolute z-20 mt-1 max-h-44 w-full overflow-y-auto rounded-md border border-border bg-popover p-0.5 shadow-md">
                      {objHits.slice(0, 8).map((o) => (
                        <button key={o.id} type="button"
                          onClick={() => { setObjectId(o.id); setObjectName(o.name); setObjQ('') }}
                          className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent">
                          {o.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
            <p className="text-[11px] text-muted-foreground">
              Заявка живёт при объекте: там ей начислятся стадия и срок. Не про
              станцию — уйдёт на «Офис».
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium">Приоритет</label>
            <Select value={priority} onValueChange={(v) => setPriority(v as typeof priority)}>
              <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Низкий</SelectItem>
                <SelectItem value="medium">Обычный</SelectItem>
                <SelectItem value="high">Высокий</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button className="w-full" size="sm" disabled={busy} onClick={send}>
            {busy && <Loader2 className="mr-1 size-3.5 animate-spin" />}
            Создать заявку
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── пересылка: выбор чатов-получателей ───────────────────────────────────────
function ForwardDialog({ message, rooms, onClose, onDone }: {
  message: ChatMessage
  rooms: ChatRoom[]
  onClose: () => void
  onDone: (roomIds: string[]) => void
}) {
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const ids = Object.keys(picked).filter((k) => picked[k])
  const list = rooms.filter((r) => !q.trim()
    || (r.name || '').toLowerCase().includes(q.trim().toLowerCase()))
  const send = async () => {
    if (!ids.length) return
    setBusy(true)
    try {
      await chat.forwardMessage(message.id, ids)
      onDone(ids)
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось переслать')
    } finally { setBusy(false) }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-sm gap-0 p-0 sm:max-w-sm">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Переслать сообщение</DialogTitle>
        </DialogHeader>
        <div className="p-4">
          <p className="mb-2 truncate rounded-md bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
            {message.content || message.fileName || 'вложение'}
          </p>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск чата…" className="h-8 pl-8 text-xs" />
          </div>
          <div className="max-h-64 space-y-0.5 overflow-y-auto">
            {list.map((r) => (
              <button key={r.id} type="button"
                onClick={() => setPicked((p) => ({ ...p, [r.id]: !p[r.id] }))}
                className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent',
                  picked[r.id] && 'bg-primary/10')}>
                <span className="min-w-0 flex-1 truncate">{r.name || 'Личная переписка'}</span>
                {picked[r.id] && <Check className="size-4 shrink-0 text-primary" />}
              </button>
            ))}
            {list.length === 0 && <p className="py-4 text-center text-xs text-muted-foreground">Чатов не найдено</p>}
          </div>
          <Button className="mt-3 w-full" size="sm" disabled={!ids.length || busy} onClick={send}>
            {busy && <Loader2 className="mr-1 size-3.5 animate-spin" />}
            Переслать{ids.length > 1 ? ` (${ids.length})` : ''}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── карточка человека: «кто это» по клику на участника или автора сообщения ──
/** Своё фото: клик по кружку — выбрать файл, крестик — убрать. */
function MyAvatarPicker({ current, name, userId }: {
  current?: string | null; name?: string | null; userId: string
}) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const { companyId } = useCompany()

  const save = async (file: File | null) => {
    setBusy(true)
    try {
      let url = ''
      if (file) {
        if (!file.type.startsWith('image/')) throw new Error('Нужна картинка')
        const up = await chat.uploadAttachment(file, companyId)
        url = up.fileUrl
      }
      await chat.updateMe({ avatarUrl: url })
      // Фото стоит в составе комнаты, в ленте и в карточке — обновляем всё разом.
      qc.invalidateQueries({ queryKey: ['chat-user-profile', userId] })
      qc.invalidateQueries({ queryKey: ['chat-room-detail'] })
      toast.success(file ? 'Фото обновлено' : 'Фото убрано')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить фото')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative">
      <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}
        title="Сменить фото" className="block">
        <Avatar seed={userId} name={name} size={40} src={current} />
        {busy && <Loader2 className="absolute inset-0 m-auto size-4 animate-spin text-white" />}
      </button>
      {current && !busy && (
        <button type="button" onClick={() => save(null)} title="Убрать фото"
          className="absolute -right-1 -top-1 rounded-full bg-card p-0.5 text-muted-foreground hover:text-destructive">
          <X className="size-3" />
        </button>
      )}
      <input ref={fileRef} type="file" accept="image/*" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) save(f); e.target.value = '' }} />
    </div>
  )
}

function PersonProfileDialog({ userId, online, selfId, onClose, onMessage }: {
  userId: string
  online?: boolean
  selfId?: string
  onClose: () => void
  onMessage: (uid: string) => void
}) {
  const { data: p, isLoading } = useQuery({
    queryKey: ['chat-user-profile', userId],
    queryFn: () => chat.getUserProfile(userId),
    retry: false,
  })
  const seen = p?.lastSeenAt
    ? new Date(p.lastSeenAt).toLocaleString('ru-RU',
        { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : null
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-xs gap-0 p-0 sm:max-w-xs">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Кто это</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 p-4">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Загрузка…
            </div>
          )}
          {!isLoading && !p && (
            <div className="text-sm text-muted-foreground">Сведений нет: человек не из вашего пространства.</div>
          )}
          {p && (
            <>
              <div className="flex items-center gap-3">
                {/* Своё фото меняется прямо здесь: отдельного экрана «мой профиль»
                    ради одной картинки заводить незачем. */}
                {p.userId === selfId ? (
                  <MyAvatarPicker current={p.avatarUrl} name={p.name} userId={p.userId} />
                ) : (
                  <Avatar seed={p.userId} name={p.name} online={online} size={40} src={p.avatarUrl} />
                )}
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-semibold">{p.name}</span>
                    <PartyBadge party={{
                      partyType: p.partyType ?? 'internal',
                      role: p.role === 'admin' ? 'admin' : undefined,
                      orgName: p.organizationName,
                    }} />
                    {p.mailOnly && (
                      <span className="shrink-0 rounded border border-border px-1 text-[10px] text-muted-foreground">по почте</span>
                    )}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">{p.email}</div>
                </div>
              </div>
              <dl className="space-y-1 text-xs">
                {p.position && (
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-muted-foreground">Должность</dt>
                    <dd className="min-w-0 truncate">{p.position}</dd>
                  </div>
                )}
                {p.organizationName && (
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-muted-foreground">Компания</dt>
                    <dd className="min-w-0 truncate">{p.organizationName}</dd>
                  </div>
                )}
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-muted-foreground">Уровень</dt>
                  <dd>{p.role === 'admin' ? 'администратор организации' : 'сотрудник'}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-20 shrink-0 text-muted-foreground">Сейчас</dt>
                  <dd>{online ? 'в сети' : seen ? `заходил(а) ${seen}` : 'ещё не заходил(а)'}</dd>
                </div>
              </dl>
              {p.userId !== selfId && (
                <Button size="sm" className="h-8 w-full" onClick={() => onMessage(p.userId)}>
                  <MessageCircle className="mr-1.5 size-4" /> Написать лично
                </Button>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── диалог создания чата (личный / группа) ────────────────────────────────────
function CreateChatDialog({ open, onOpenChange, onCreated, scopeProduct }: {
  open: boolean; onOpenChange: (o: boolean) => void; onCreated: (roomId: string) => void
  /** Контекст рельсы: группа, созданная из приложения, по умолчанию его и держится. */
  scopeProduct?: string | null
}) {
  const { companyId } = useCompany()
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [groupName, setGroupName] = useState('')
  // Привязка к приложению — та самая пометка «специализированная группа»: рельса
  // этого приложения покажет её первой, остальные приложения — не покажут вовсе.
  const [scopeSel, setScopeSel] = useState<string>(scopeProduct || 'none')
  const [busy, setBusy] = useState(false)
  const { data: users = [] } = useQuery({
    queryKey: ['chat-user-search', companyId, q],
    queryFn: () => chat.searchUsers(q),
    enabled: open,
  })
  const ids = Object.keys(picked)
  const isGroup = ids.length > 1
  useEffect(() => {
    if (!open) { setQ(''); setPicked({}); setGroupName(''); setScopeSel(scopeProduct || 'none') }
  }, [open, scopeProduct])
  async function create() {
    if (!ids.length) return
    setBusy(true)
    try {
      const room = isGroup
        ? await chat.createRoom('group', ids, groupName.trim() || `Группа (${ids.length + 1})`,
            scopeSel === 'none' ? null : scopeSel)
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
            <>
              <Input placeholder="Название группы" value={groupName} onChange={(e) => setGroupName(e.target.value)} className="mb-2 h-8" />
              <Select value={scopeSel} onValueChange={setScopeSel}>
                <SelectTrigger className="mb-2 h-8 text-xs">
                  <SelectValue placeholder="Приложение" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Всё пространство</SelectItem>
                  {SPACE_PRODUCTS.map((p) => (
                    <SelectItem key={p.code} value={p.code}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
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
                <Avatar seed={u.userId} name={u.name} online={u.online} size={32} src={u.avatarUrl} />
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
  onAuthorClick, authorAvatar, withAvatar, onReact, onPin, onForward, onTicket, onImageClick,
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
  /** Фото автора: в групповом чате оно слева от пузыря, как в привычных мессенджерах. */
  authorAvatar?: string | null
  /** Показывать колонку аватара (группа/канал, чужое сообщение). */
  withAvatar?: boolean
  onReact?: (emoji: string) => void
  onPin?: () => void
  onForward?: () => void
  onTicket?: () => void
  onImageClick?: (path: string) => void
}) {
  const { isFirstInGroup, isLastInGroup, showDate } = grouping
  // Ответ свайпом: сдвиг пузыря вправо ставит его в цитату — привычный жест
  // мобильных мессенджеров, на мыши остаётся кнопка «Ответить».
  const [swipeX, setSwipeX] = useState(0)
  const touchRef = useRef<{ x: number; y: number } | null>(null)

  // Первая ссылка сообщения — кандидат на карточку превью.
  const firstLink = useMemo(() => {
    const m = /https?:\/\/[^\s<>"']+/.exec(message.content || '')
    return m ? m[0].replace(/[.,;:!?)]+$/, '') : null
  }, [message.content])
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
      <div className={cn('group/bubble flex items-end gap-1.5', isOwn ? 'justify-end' : 'justify-start', isLastInGroup ? 'mb-2' : 'mb-[2px]')}>
        {/* Аватар автора — у последнего сообщения серии, как в мессенджерах:
            лицо стоит рядом с концом реплики, а не улетает к её началу. Место
            под него держим всегда, иначе пузыри серии съезжают по горизонтали. */}
        {withAvatar && !isOwn && (
          isLastInGroup
            ? <button type="button" onClick={onAuthorClick} disabled={!onAuthorClick} className="mb-0.5 shrink-0">
                <Avatar seed={message.userId || message.id} name={message.userName} size={26} src={authorAvatar} />
              </button>
            : <span className="w-[26px] shrink-0" />
        )}
        <div className={cn(
          'relative max-w-[85%] px-2.5 py-1.5',
          bubbleRadius(isOwn, isFirstInGroup, isLastInGroup),
          isOwn ? 'bg-primary text-primary-foreground' : 'bg-muted',
        )}
          style={swipeX ? { transform: `translateX(${swipeX}px)`, transition: 'transform .05s linear' } : undefined}
          onTouchStart={(e) => { touchRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY } }}
          onTouchMove={(e) => {
            const start = touchRef.current
            if (!start) return
            const dx = e.touches[0].clientX - start.x
            const dy = Math.abs(e.touches[0].clientY - start.y)
            // Только горизонтальный жест: вертикальный — это прокрутка ленты.
            if (dy > 24) { touchRef.current = null; setSwipeX(0); return }
            setSwipeX(Math.max(0, Math.min(dx, 64)))
          }}
          onTouchEnd={() => {
            // Порог в 44 px: случайное касание при прокрутке не должно
            // подставлять цитату, а осознанный сдвиг — должен.
            if (swipeX > 44) onReply()
            touchRef.current = null
            setSwipeX(0)
          }}>
          {/* Меню действий: hover на мыши, всегда видно на тач-устройствах */}
          <div className={cn(
            'absolute -top-5 z-10 flex items-center gap-0.5 rounded-lg border border-border bg-popover px-1 py-1 shadow-lg opacity-0 transition-opacity group-hover/bubble:opacity-100 [@media(pointer:coarse)]:opacity-100',
            isOwn ? 'right-0' : 'left-0',
          )}>
            {/* Цель клика — 28px, а не размер самого символа: реакции ставят мышью на
                ходу, и в 14-пиксельный эмодзи попасть нельзя. Символ крупнее рамки
                кнопки не делаем — иначе панель выше самого сообщения. */}
            {onReact && QUICK_REACTIONS.map((emoji) => (
              <button key={emoji} onClick={() => onReact(emoji)} title={emoji}
                className="flex size-7 items-center justify-center rounded-md text-[18px] leading-none transition-transform hover:scale-110 hover:bg-accent active:scale-95">
                {emoji}
              </button>
            ))}
            {onReact && <span className="mx-0.5 h-5 w-px bg-border" />}
            <button onClick={onReply} title="Ответить"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><Reply className="size-4" /></button>
            {onForward && <button onClick={onForward} title="Переслать"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><Forward className="size-4" /></button>}
            {onTicket && <button onClick={onTicket} title="Создать заявку из сообщения"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><ClipboardList className="size-4" /></button>}
            {onPin && <button onClick={onPin} title="Закрепить"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><Pin className="size-4" /></button>}
            {isOwn && <button onClick={onEditStart} title="Редактировать"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"><Pencil className="size-4" /></button>}
            {canDelete && <button onClick={onDelete} title="Удалить"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-red-500"><Trash2 className="size-4" /></button>}
          </div>

          {!isOwn && isFirstInGroup && (
            <div className="mb-0.5 flex items-center gap-1.5">
              <button type="button" onClick={onAuthorClick} disabled={!onAuthorClick}
                title={onAuthorClick ? 'Кто это — карточка человека' : undefined}
                className={cn('text-left text-[11px] font-semibold', getUserColor(message.userId || ''), onAuthorClick && 'cursor-pointer hover:underline')}>
                {message.userName || 'Пользователь'}
              </button>
              {/* Кто говорит — у самого сообщения, а не только в составе комнаты:
                  инженера поддержки платформы, своего сотрудника и человека партнёра
                  надо различать в момент чтения, не сверяясь со списком участников. */}
              {message.authorParty && message.authorParty !== 'internal' && (
                <PartyBadge party={{ partyType: message.authorParty }} className="py-0" />
              )}
            </div>
          )}

          {message.forwardedFrom && (
            <div className={cn('mb-0.5 flex items-center gap-1 text-[11px] italic',
              isOwn ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
              <Forward className="size-3" /> Переслано от {message.forwardedFrom}
            </div>
          )}

          {/* Пришло письмом: собеседник читает разговор в своей почте и отвечает
              оттуда же. Без пометки его молчание читается как «не заходил», хотя
              заходить ему некуда. */}
          {message.externalSource === 'email' && (
            <div className={cn('mb-0.5 flex items-center gap-1 text-[11px]',
              isOwn ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
              <Mail className="size-3" /> письмом
            </div>
          )}

          {/* Цитата красится ОТ ФОНА пузыря: на синем исходящем синяя рамка и
              голубое имя сливались в нечитаемое пятно (замечание МАГа 31.07.2026). */}
          {message.replyTo && message.replyPreview && (
            <div className={cn('mb-1 rounded-md border-l-2 py-0.5 pl-2 pr-1.5',
              isOwn ? 'border-white/80 bg-white/15' : 'border-primary bg-primary/10')}>
              <div className={cn('text-[11px] font-semibold',
                isOwn ? 'text-white' : 'text-primary')}>
                {message.replyAuthor || 'Пользователь'}
              </div>
              <div className={cn('max-w-[220px] truncate text-[11px]',
                isOwn ? 'text-primary-foreground/85' : 'text-foreground/75')}>
                {message.replyPreview}
              </div>
            </div>
          )}

          {isEditing ? (
            <div className="space-y-1">
              <textarea autoFocus value={editText} onChange={(e) => onEditTextChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onEditSave() }
                  if (e.key === 'Escape') onEditCancel()
                }}
                className="min-h-[28px] w-full resize-none rounded border border-border bg-transparent p-1 text-[13px] outline-none focus:border-primary" rows={2} />
              <div className="flex justify-end gap-1">
                <button onClick={onEditCancel} className="rounded p-0.5 text-muted-foreground hover:bg-accent"><X className="size-3.5" /></button>
                <button onClick={onEditSave} className="rounded p-0.5 text-emerald-500 hover:bg-accent"><Check className="size-3.5" /></button>
              </div>
            </div>
          ) : (
            message.content && (
              <>
                <p className="whitespace-pre-wrap break-words text-[13px] leading-[1.45]">
                  {searchHighlight ? highlightText(message.content, searchHighlight) : linkifyText(message.content)}
                  <span className={cn('inline-block', isOwn ? 'w-16' : 'w-11')} />
                </p>
                {/* Первая ссылка сообщения разворачивается в карточку: «посмотри
                    вот это» перестаёт требовать открытия вкладки. */}
                {firstLink && <LinkCard url={firstLink} mine={isOwn} />}
              </>
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
                /* Подсказка перечисляет ИМЕНА: «1» без автора не отвечает на вопрос,
                   кто это поставил, — а в группе это первое, что хотят знать. */
                <button key={r.emoji} onClick={() => onReact?.(r.emoji)}
                  title={r.users?.length ? r.users.join(', ') : undefined}
                  className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[13px] leading-4 transition-colors',
                    isOwn
                      ? (r.mine
                          ? 'border-white/80 bg-white/25 text-white'
                          : 'border-white/35 bg-white/10 text-primary-foreground/90 hover:border-white/60')
                      : (r.mine
                          ? 'border-primary/60 bg-primary/15 text-primary'
                          : 'border-border bg-background/60 text-muted-foreground hover:border-foreground/30'))}>
                  {r.emoji}<span className="text-[10px] tabular-nums">{r.count}</span>
                </button>
              ))}
            </div>
          )}

          <span className={cn('absolute bottom-1 right-2 flex items-center gap-0.5 text-[10px]', isOwn ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
            {message.isEdited && <span className="text-[10px] opacity-70">ред.</span>}
            {formatTime(message.createdAt)}
            {isOwn && (
              <span className={cn('text-[10px]', message.readCount > 0 && 'text-sky-300')}
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
export function ChatPanel({ compact, scopeProduct }: {
  compact?: boolean
  /**
   * Приложение, из которого открыта панель. Правая рельса передаёт текущее приложение
   * и получает его чаты плюс общие чаты пространства; верхняя кнопка не передаёт
   * ничего и показывает всё. Один и тот же чат — разные предустановки.
   */
  scopeProduct?: string | null
} = {}) {
  const { user } = useAuth()
  const { companyId } = useCompany()
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
  // «Кто это» по клику на человека: участника в составе или автора сообщения.
  const [profileFor, setProfileFor] = useState<string | null>(null)
  // Пересылка: сообщение, для которого открыт выбор чатов-получателей.
  const [forwardMsg, setForwardMsg] = useState<ChatMessage | null>(null)
  // «В заявку»: сообщение, из которого создаётся заявка.
  const [ticketMsg, setTicketMsg] = useState<ChatMessage | null>(null)
  // Разрешение на браузерные уведомления — для кнопки-колокольчика в шапке списка.
  const [pushPerm, setPushPerm] = useState<NotificationPermission | 'unsupported'>(
    () => (pushSupported() ? Notification.permission : 'unsupported'))
  // Ширина колонки списка: тянется разделителем, помнится между сессиями.
  const [listWidth, setListWidth] = useState(() => {
    const saved = Number(localStorage.getItem('cl-chat-list-width'))
    return saved >= 200 && saved <= 560 ? saved : 288
  })
  const startResize = (e: React.PointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = listWidth
    const move = (ev: PointerEvent) => {
      const next = Math.min(560, Math.max(200, startW + ev.clientX - startX))
      setListWidth(next)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.style.userSelect = ''
      setListWidth((w) => { localStorage.setItem('cl-chat-list-width', String(w)); return w })
    }
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
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

  // Область: открыв рельсу в «Топливе», человек ждёт чаты «Топлива», а не весь
  // пространственный список — группы «Магазина» и «Процессинга» здесь только мешают.
  // Поэтому контекст включён по умолчанию, а выйти к остальным можно одним щелчком.
  const [scopeOn, setScopeOn] = useState(true)
  const scope = scopeOn ? scopeProduct : null
  const scopeName = scopeProduct
    ? SPACE_PRODUCTS.find((p) => p.code === scopeProduct)?.label || scopeProduct
    : null

  // ── данные ──
  const { data: rooms = [] } = useQuery({
    queryKey: ['chat-rooms', companyId, showArchived, scope ?? 'all'],
    queryFn: () => chat.getRooms(showArchived, scope),
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
    queryKey: ['chat-folders', companyId],
    queryFn: () => chat.getFolders(),
  })
  const { data: presence = [] } = useQuery({
    queryKey: ['chat-presence', companyId],
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
        // Звук — на чужое сообщение и только если человек не смотрит в этот чат:
        // пикать на собственную отправку и на открытую переписку незачем.
        if (e.userId && String(e.userId) !== user?.id
            && (String(e.roomId ?? '') !== selectedRoom || document.hidden)) beep()
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
      if (selectedRoom) localStorage.removeItem(`cl-draft-${selectedRoom}`)
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
  // Тихая переподписка Web Push: разрешение уже дано — восстановить подписку после
  // чистки браузера или пересоздания SW. Один раз на открытие чата.
  useEffect(() => { ensurePushSubscription().catch(() => {}) }, [])
  // Открытие конкретной комнаты извне: карточка объекта зовёт
  // openInteraction('chat', 'room:<id>') — контекст доносит, какой чат показать.
  const { interactionContext } = useSupportContext()
  useEffect(() => {
    if (interactionContext?.startsWith('room:')) {
      setSelectedRoom(interactionContext.slice(5))
      setShowRoomInfo(false)
    }
  }, [interactionContext])
  // Черновики: набранное живёт per-чат. Уход из комнаты сохраняет текст, вход —
  // восстанавливает; отправка чистит (в sendMutation.onSuccess).
  // ponytail: localStorage, без синка между устройствами — добавить серверное поле,
  // если понадобится продолжать с телефона.
  const msgTextRef = useRef('')
  useEffect(() => { msgTextRef.current = messageText }, [messageText])
  const prevRoomRef = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevRoomRef.current
    if (prev && prev !== selectedRoom) {
      const t = msgTextRef.current.trim()
      if (t) localStorage.setItem(`cl-draft-${prev}`, t)
      else localStorage.removeItem(`cl-draft-${prev}`)
    }
    if (selectedRoom && selectedRoom !== prev) {
      setMessageText(localStorage.getItem(`cl-draft-${selectedRoom}`) || '')
    }
    prevRoomRef.current = selectedRoom
  }, [selectedRoom])

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
  // Скрытые комнаты (чат заявки) в общий список не входят — их шапку и права
  // строим из детали; роль зрителя деталь отдаёт сама (myRole).
  const activeRoom = useMemo(() => {
    const inList = selectedRoom ? rooms.find((r) => r.id === selectedRoom) : undefined
    if (inList) return inList
    if (roomDetail && roomDetail.id === selectedRoom) return { ...roomDetail, unreadCount: 0 }
    return undefined
  }, [rooms, selectedRoom, roomDetail])
  const isAdmin = user?.role === 'admin' || !!user?.is_superadmin
  // Канал односторонний: писать в него могут владелец и назначенные им админы —
  // роль В КОМНАТЕ, а не должность в компании. «Объявления» пространства ведёт ещё и
  // администратор компании: это канал самой организации, а канал платформы — наш,
  // пространство его только читает.
  const canWrite = (() => {
    if (!activeRoom) return true
    const roomRole = activeRoom.myRole || 'member'
    if (activeRoom.kind === 'platform') return false
    if (activeRoom.kind === 'news') {
      return NEWS_WRITER_ROLES.has(user?.role || '') || roomRole === 'owner' || roomRole === 'admin'
    }
    if (activeRoom.type === 'channel') return roomRole === 'owner' || roomRole === 'admin'
    return true
  })()
  const peerPresence = activeRoom?.type === 'direct' && activeRoom.directPeerId ? presenceMap.get(activeRoom.directPeerId) : undefined

  const filteredRooms = useMemo(() => {
    const custom = folders.find((f) => f.id === folder)
    const s = listSearch.trim().toLowerCase()
    const visible = rooms.filter((r) => {
      // «Объявления» пространства — тоже канал по смыслу: писать может только админ.
      if (folder === 'channel' && !(r.type === 'channel' || r.kind === 'news')) return false
      if (folder === 'group' && !(r.type === 'group' || r.kind === 'general')) return false
      if (folder === 'direct' && r.type !== 'direct') return false
      if (custom && !custom.roomIds.includes(r.id)) return false
      return !s || (r.name || '').toLowerCase().includes(s) || (r.lastMessage || '').toLowerCase().includes(s)
    })
    // Порядок как в привычных мессенджерах: закреплённые сверху, дальше по
    // свежести разговора. Прежняя сортировка держала «Общий чат» и «Объявления»
    // первыми всегда — активная переписка уезжала вниз под молчащие каналы.
    // Системный ранг остался тай-брейком для чатов без сообщений.
    const rank = (r: ChatRoom) => (r.kind === 'general' ? 0 : r.kind === 'news' ? 1 : 2)
    const at = (r: ChatRoom) => (r.lastMessageAt ? Date.parse(r.lastMessageAt) : 0)
    return [...visible].sort((a, b) => {
      if (!!a.isPinned !== !!b.isPinned) return a.isPinned ? -1 : 1
      const d = at(b) - at(a)
      if (d) return d
      return rank(a) - rank(b)
    })
  }, [rooms, listSearch, folder, folders])

  const unreadByFolder = useMemo(() => {
    const acc: Record<string, number> = { all: 0, channel: 0, group: 0, direct: 0 }
    for (const f of folders) acc[f.id] = 0
    for (const r of rooms) {
      const n = r.unreadCount || 0
      acc.all += n
      if (r.type === 'channel' || r.kind === 'news') acc.channel += n
      else if (r.type === 'group' || r.kind === 'general') acc.group += n
      if (r.type === 'direct') acc.direct += n
      for (const f of folders) if (f.roomIds.includes(r.id)) acc[f.id] += n
    }
    return acc
  }, [rooms, folders])
  const totalUnread = useMemo(() => rooms.reduce((a, r) => a + (r.unreadCount || 0), 0), [rooms])

  const [showMedia, setShowMedia] = useState(false)

  // Прокрутка к найденному сообщению: id цели ставит поиск, эффект ниже доезжает
  // до неё, как только лента отрисована, и на пару секунд подсвечивает.
  const [jumpTo, setJumpTo] = useState<string | null>(null)
  const msgRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  useEffect(() => {
    if (!jumpTo) return
    const el = msgRefs.current.get(jumpTo)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('ring-2', 'ring-primary', 'rounded-lg')
    const t = setTimeout(() => {
      el.classList.remove('ring-2', 'ring-primary', 'rounded-lg')
      setJumpTo(null)
    }, 2200)
    return () => clearTimeout(t)
  }, [jumpTo, messages])

  // Звук входящего: тихий двойной сигнал, только когда сообщение пришло не от
  // меня и не в открытый чат. Файла нет намеренно — короткий тон рисуется
  // осциллятором, лишний ассет в сборке ради двух нот не нужен.
  const [soundOn, setSoundOn] = useState(() => localStorage.getItem('cl-chat-sound') !== 'off')
  useEffect(() => { localStorage.setItem('cl-chat-sound', soundOn ? 'on' : 'off') }, [soundOn])
  const beep = useCallback(() => {
    if (!soundOn) return
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctx()
      const play = (freq: number, at: number) => {
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.frequency.value = freq
        osc.type = 'sine'
        gain.gain.setValueAtTime(0.0001, ctx.currentTime + at)
        gain.gain.exponentialRampToValueAtTime(0.06, ctx.currentTime + at + 0.01)
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.16)
        osc.connect(gain); gain.connect(ctx.destination)
        osc.start(ctx.currentTime + at); osc.stop(ctx.currentTime + at + 0.18)
      }
      play(880, 0); play(1170, 0.09)
      setTimeout(() => ctx.close().catch(() => {}), 600)
    } catch { /* браузер не дал звук — не беда, есть бейдж и push */ }
  }, [soundOn])

  // Фон ленты: личная настройка, живёт в браузере (см. CHAT_SKINS).
  const [skin, setSkin] = useState<string>(() => localStorage.getItem('cl-chat-skin') || 'none')
  useEffect(() => { localStorage.setItem('cl-chat-skin', skin) }, [skin])

  // Непрочитанные видны в заголовке вкладки: человек работает в другом окне, и
  // единственное, что до него дотягивается, — строка «(3) …» в списке вкладок.
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\)\s*/, '')
    document.title = totalUnread > 0 ? `(${totalUnread}) ${base}` : base
    return () => { document.title = document.title.replace(/^\(\d+\)\s*/, '') }
  }, [totalUnread])

  // Сколько было непрочитано в момент открытия чата: линия «непрочитанные»
  // должна стоять там, где человек остановился, и не съезжать вниз, пока он
  // читает. Считаем от конца ленты, поэтому число, а не id сообщения.
  const [unreadFrom, setUnreadFrom] = useState<number | null>(null)
  useEffect(() => {
    const n = rooms.find((r) => r.id === selectedRoom)?.unreadCount || 0
    setUnreadFrom(n > 0 ? n : null)
    // Только на смену комнаты: перечитывание rooms не должно двигать линию.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRoom])

  // Фото авторов берём из состава комнаты — он уже загружен. Отдельный запрос
  // на аватары авторов страницы был бы вторым источником тех же данных.
  const avatarByUser = useMemo(() => {
    const m = new Map<string, string | null>()
    for (const p of roomDetail?.participants || []) m.set(p.userId, p.avatarUrl ?? null)
    return m
  }, [roomDetail])

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
          {/* Уведомления при закрытой вкладке: колокольчик виден, пока разрешение не
              спрошено. После «granted» подписка живёт сама (тихая переподписка). */}
          {pushPerm === 'default' && (
            <button title="Включить уведомления браузера о новых сообщениях"
              onClick={() => requestPushPermission().then((r) => {
                setPushPerm(pushSupported() ? Notification.permission : 'unsupported')
                if (r === 'ok') toast.success('Уведомления включены')
                else if (r === 'denied') toast.error('Уведомления запрещены в браузере')
              })}
              className="inline-flex size-7 items-center justify-center rounded-md text-primary transition-colors hover:bg-accent">
              <Bell className="size-4" />
            </button>
          )}
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
        {/* Область: сначала чаты этого приложения (плюс общие пространства и личные),
            и один щелчок, чтобы выйти ко всем. Виден сам факт отбора — иначе непонятно,
            почему список короче, чем в приложении «Чаты». */}
        {scopeName && (
          <div className="mt-2 inline-flex w-full rounded-md border border-border p-0.5">
            {[{ on: true, l: scopeName }, { on: false, l: 'Всё пространство' }].map((o) => (
              <button key={String(o.on)} type="button" onClick={() => setScopeOn(o.on)}
                title={o.on ? `Чаты приложения «${scopeName}» и общие чаты пространства`
                  : 'Все чаты, где вы участник'}
                className={cn('flex-1 truncate rounded-[5px] px-2 py-1 text-[11px] transition-colors',
                  scopeOn === o.on ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground')}>
                {o.l}
              </button>
            ))}
          </div>
        )}
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
            || room.kind === 'platform'
          const peerOnline = room.type === 'direct' && room.directPeerId ? presenceMap.get(room.directPeerId)?.online : false
          return (
            <div key={room.id} onClick={() => { setSelectedRoom(room.id); setShowRoomInfo(false) }}
              className={cn('group/room flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent',
                selectedRoom === room.id && 'bg-accent')}>
              <div className="relative">
                {/* Личный чат первым: у него фото собеседника и точка присутствия —
                    показ через AuthImage их бы потерял. */}
                {room.type === 'direct' ? (
                  <Avatar seed={room.id} name={room.name} online={!!peerOnline} size={40} src={room.avatarUrl} />
                ) : room.avatarUrl ? (
                  <AuthImage path={room.avatarUrl} alt={room.name || 'Чат'}
                    className="size-10 shrink-0 rounded-full object-cover" />
                ) : isSystem ? (
                  <div className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground"><Icon className="size-5" /></div>
                ) : (
                  <Avatar seed={room.id} name={room.name} icon={Icon} size={40} />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-1">
                  <span className="flex min-w-0 items-center gap-1">
                    <span className="truncate text-sm font-medium">{room.name || 'Чат'}</span>
                    {/* Метка «специализированной» группы: видно, при каком она приложении. */}
                    {room.scopeProduct && (
                      <span className="shrink-0 rounded bg-primary/10 px-1 py-px text-[10px] font-medium leading-tight text-primary">
                        {SPACE_PRODUCTS.find((p) => p.code === room.scopeProduct)?.label || room.scopeProduct}
                      </span>
                    )}
                    {/* Группа «по станции»: видно, при каком объекте живёт разговор. */}
                    {room.scopeObjectName && (
                      <span className="flex min-w-0 max-w-[110px] shrink-0 items-center gap-0.5 rounded bg-emerald-500/10 px-1 py-px text-[10px] font-medium leading-tight text-emerald-600 dark:text-emerald-400"
                        title={room.scopeObjectName}>
                        <MapPin className="size-2.5 shrink-0" />
                        <span className="truncate">{room.scopeObjectName}</span>
                      </span>
                    )}
                    {isMuted(room) && <BellOff className="size-3 shrink-0 text-muted-foreground/70" />}
                    {room.isPinned && <Pin className="size-3 shrink-0 text-muted-foreground/70" />}
                  </span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <span className="text-[10px] text-muted-foreground">{fmtAge(room.lastMessageAt)}</span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button onClick={(e) => e.stopPropagation()} className="rounded p-0.5 opacity-0 transition-opacity hover:bg-muted group-hover/room:opacity-100 [@media(pointer:coarse)]:opacity-100">
                          <MoreVertical className="size-3.5 text-muted-foreground" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                        {/* Закрепление — личное: список у каждого свой, и «важное
                            сверху» не должно навязываться остальным участникам. */}
                        <DropdownMenuItem className="gap-2 text-xs"
                          onClick={() => chat.pinRoom(room.id)
                            .then(() => qc.invalidateQueries({ queryKey: ['chat-rooms'] }))
                            .catch(() => toast.error('Не удалось закрепить чат'))}>
                          <Pin className="size-3.5" />{room.isPinned ? 'Открепить' : 'Закрепить сверху'}
                        </DropdownMenuItem>
                        {/* «Без звука» доступен и системным чатам: выйти из «Объявлений»
                            нельзя, а не получать push о каждом — можно. */}
                        <DropdownMenuItem className="gap-2 text-xs"
                          onClick={() => chat.muteRoom(room.id, isMuted(room) ? null : 'forever')
                            .then(() => qc.invalidateQueries({ queryKey: ['chat-rooms'] }))
                            .catch(() => toast.error('Не удалось изменить уведомления'))}>
                          {isMuted(room)
                            ? <><Bell className="size-3.5" />Со звуком</>
                            : <><BellOff className="size-3.5" />Без звука</>}
                        </DropdownMenuItem>
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
                    {(() => {
                      // Черновик заметнее последнего сообщения: человек сам не дописал.
                      const draft = !room.unreadCount && localStorage.getItem(`cl-draft-${room.id}`)
                      if (draft) return <><span className="text-amber-600 dark:text-amber-500">Черновик:</span> {draft}</>
                      return <>
                        {room.pinnedMessage && <Pin className="mr-1 inline size-3 text-primary" />}
                        {room.lastMessage || 'Нет сообщений'}
                      </>
                    })()}
                  </p>
                  {(room.unreadCount ?? 0) > 0 && (
                    <span className={cn('shrink-0 rounded-full px-1.5 text-[10px] font-bold',
                      isMuted(room) ? 'bg-muted-foreground/30 text-foreground/80' : 'bg-primary text-primary-foreground')}>
                      {room.unreadCount}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
        {/* Глобальный поиск: тот же ввод, что фильтрует комнаты, от трёх символов
            ищет и по содержимому сообщений всех чатов. */}
        <GlobalSearchResults q={listSearch}
          onOpen={(roomId, messageId) => {
            setSelectedRoom(roomId)
            setMessageSearch(listSearch)
            setShowMessageSearch(true)
            setShowRoomInfo(false)
            // Найденное сообщение может быть глубоко в истории: открыть чат мало,
            // надо к нему доехать — иначе человек ищет глазами то, что уже нашли.
            setJumpTo(messageId)
          }} />
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
            {activeRoom?.avatarUrl ? (
              <AuthImage path={activeRoom.avatarUrl} alt={activeRoom.name || 'Чат'}
                className="size-8 shrink-0 rounded-full object-cover" />
            ) : activeRoom?.kind === 'news' || activeRoom?.kind === 'general' ? (
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
        <button onClick={() => setShowMedia(true)} title="Вложения чата"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
          <Images className="size-4" />
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button title="Оформление и звук"
              className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <Palette className="size-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="text-[13px]">
            {Object.entries(CHAT_SKINS).map(([key, s]) => (
              <DropdownMenuItem key={key} className="gap-2 text-xs" onClick={() => setSkin(key)}>
                {skin === key ? <Check className="size-3.5" /> : <span className="size-3.5" />}
                {s.label}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            {/* Звук здесь же: и фон, и сигнал — про то, как чат ощущается лично мне. */}
            <DropdownMenuItem className="gap-2 text-xs" onClick={() => setSoundOn((v) => !v)}>
              {soundOn ? <><Volume2 className="size-3.5" />Звук включён</> : <><VolumeX className="size-3.5" />Звук выключен</>}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
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
          canManage={isAdmin || activeRoom?.createdBy === user?.id
            || activeRoom?.myRole === 'owner' || activeRoom?.myRole === 'admin'}
          canOwn={isAdmin || activeRoom?.createdBy === user?.id || activeRoom?.myRole === 'owner'}
          onAdd={(uid) => { chat.addParticipant(selectedRoom!, uid).then(() => { qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success('Участник добавлен') }).catch(() => toast.error('Не удалось добавить')) }}
          onMailAdded={() => qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] })}
          onRename={(name) => { chat.patchRoom(selectedRoom!, { name }).then(() => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success('Чат переименован') }).catch((e: Error) => toast.error(e.message || 'Не удалось переименовать')) }}
          onAvatar={(file) => {
            const apply = (url: string) => chat.patchRoom(selectedRoom!, { avatarUrl: url })
              .then(() => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success(url ? 'Аватар обновлён' : 'Аватар убран') })
              .catch((e: Error) => toast.error(e.message || 'Не удалось обновить аватар'))
            if (!file) { apply(''); return }
            chat.uploadAttachment(file, user?.default_company_id)
              .then((r) => apply(r.fileUrl))
              .catch(() => toast.error('Не удалось загрузить файл'))
          }}
          onScope={(code) => { chat.patchRoom(selectedRoom!, { scopeProduct: code }).then(() => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success(code ? 'Группа привязана к приложению' : 'Группа отвязана — чат всего пространства') }).catch((e: Error) => toast.error(e.message || 'Не удалось сменить привязку')) }}
          onObject={(objectId) => { chat.patchRoom(selectedRoom!, { scopeObjectId: objectId }).then(() => { qc.invalidateQueries({ queryKey: ['chat-rooms'] }); qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success(objectId ? 'Группа привязана к объекту' : 'Группа отвязана от объекта') }).catch((e: Error) => toast.error(e.message || 'Не удалось сменить привязку')) }}
          onRemove={(uid) => { chat.removeParticipant(selectedRoom!, uid).then(() => { qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); qc.invalidateQueries({ queryKey: ['chat-rooms'] }); toast.success('Участник убран из чата') }).catch((e: Error) => toast.error(e.message || 'Не удалось убрать участника')) }}
          onSetRole={(uid, role) => { chat.setParticipantRole(selectedRoom!, uid, role).then(() => { qc.invalidateQueries({ queryKey: ['chat-room-detail', selectedRoom] }); toast.success(role === 'admin' ? 'Назначен админом чата' : 'Роль снята — участник') }).catch((e: Error) => toast.error(e.message || 'Не удалось изменить роль')) }}
          onLeave={() => { chat.leaveRoom(selectedRoom!).then(() => { setShowRoomInfo(false); setSelectedRoom(null); qc.invalidateQueries({ queryKey: ['chat-rooms'] }); toast.success('Вы вышли из группы') }).catch((e: Error) => toast.error(e.message || 'Не удалось выйти')) }}
          onShowProfile={(uid) => setProfileFor(uid)}
          onMessageUser={(uid) => openDirectMutation.mutate(uid)} presenceMap={presenceMap} />
      ) : (
        <>
          {/* Закреп */}
          {activeRoom?.pinnedMessage && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border/50 bg-muted/40 px-3 py-1.5">
              <Pin className="size-3 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="text-[10px] font-medium text-primary">Закреплено · {activeRoom.pinnedMessage.userName || ''}</div>
                <div className="truncate text-[11px] text-muted-foreground">{activeRoom.pinnedMessage.content}</div>
              </div>
              <button onClick={() => pinMutation.mutate(null)} className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground" title="Открепить"><X className="size-3" /></button>
            </div>
          )}

          {/* Лента. Фон — личная настройка: он ничего не значит для других
              участников, поэтому живёт в браузере, а не в базе пространства.
              Файл можно просто бросить в переписку — это привычнее, чем искать
              скрепку, и ровно так работают мессенджеры. */}
          <div className={cn('flex-1 overflow-y-auto', dragOver && 'ring-2 ring-inset ring-primary')}
            style={CHAT_SKINS[skin]?.style}
            onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDragOver(true) } }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              if (!e.dataTransfer.files.length) return
              e.preventDefault(); setDragOver(false)
              setPendingFiles((p) => [...p, ...Array.from(e.dataTransfer.files)].slice(0, 5))
            }}>
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
                    <Fragment key={msg.id}>
                    {/* Где я остановился: линия стоит перед первым непрочитанным
                        и не двигается, пока чат открыт (иначе она уезжала бы вниз
                        с каждым новым сообщением и теряла смысл). */}
                    {unreadFrom !== null && index === messages.length - unreadFrom && (
                      <div className="my-2 flex items-center gap-2">
                        <span className="h-px flex-1 bg-primary/40" />
                        <span className="text-[10px] uppercase tracking-wide text-primary">непрочитанные</span>
                        <span className="h-px flex-1 bg-primary/40" />
                      </div>
                    )}
                    <div ref={(el) => { if (el) msgRefs.current.set(msg.id, el); else msgRefs.current.delete(msg.id) }}>
                    <ChatBubble message={msg} album={album} isOwn={isOwn} grouping={grouping[index]}
                      canDelete={isOwn || isAdmin || activeRoom?.createdBy === user?.id}
                      editingId={editingId} editText={editText} searchHighlight={messageSearch}
                      onReply={() => setReplyTo(msg)}
                      onEditStart={() => { setEditingId(msg.id); setEditText(msg.content) }}
                      onEditCancel={() => { setEditingId(null); setEditText('') }}
                      onEditSave={() => editMutation.mutate({ id: msg.id, content: editText })}
                      onEditTextChange={setEditText}
                      onDelete={() => deleteMutation.mutate(msg.id)}
                      onAuthorClick={!isOwn && msg.userId && activeRoom?.type !== 'direct' ? () => setProfileFor(msg.userId!) : undefined}
                      withAvatar={activeRoom?.type !== 'direct'}
                      authorAvatar={msg.userId ? avatarByUser.get(msg.userId) : null}
                      onReact={(emoji) => reactMutation.mutate({ id: msg.id, emoji })}
                      onPin={() => pinMutation.mutate(msg.id)}
                      onForward={() => setForwardMsg(msg)}
                      onTicket={activeRoom?.type !== 'direct' ? () => setTicketMsg(msg) : undefined}
                      onImageClick={openImage} />
                    </div>
                    </Fragment>
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
              <div className="h-6 w-0.5 shrink-0 rounded-full bg-primary" />
              <div className="min-w-0 flex-1">
                <div className="text-[10px] font-medium text-primary">{replyTo.userName}</div>
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
                      <Avatar seed={p.userId} name={p.name} size={24} src={p.avatarUrl} />
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
                <Popover>
                  <PopoverTrigger asChild>
                    <button disabled={uploading || sendMutation.isPending} title="Эмодзи"
                      className="inline-flex size-8 max-md:size-10 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50">
                      <Smile className="size-4" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent align="start" side="top" className="w-auto p-0">
                    <EmojiPicker onPick={(e) => setMessageText((t) => t + e)} />
                  </PopoverContent>
                </Popover>
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
      {showMedia && selectedRoom && (
        <RoomMediaDialog roomId={selectedRoom} onClose={() => setShowMedia(false)} onImageClick={openImage} />
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
      {profileFor && (
        <PersonProfileDialog userId={profileFor} selfId={user?.id}
          online={presenceMap.get(profileFor)?.online}
          onClose={() => setProfileFor(null)}
          onMessage={(uid) => { setProfileFor(null); openDirectMutation.mutate(uid) }} />
      )}
      {forwardMsg && (
        <ForwardDialog message={forwardMsg} rooms={rooms.filter((r) => !r.isArchived)}
          onClose={() => setForwardMsg(null)}
          onDone={(ids) => {
            setForwardMsg(null)
            toast.success(ids.length > 1 ? `Переслано в ${ids.length} чата(ов)` : 'Переслано')
            qc.invalidateQueries({ queryKey: ['chat-rooms'] })
            qc.invalidateQueries({ queryKey: ['chat-messages'] })
          }} />
      )}
      {ticketMsg && (
        <TicketFromMessageDialog message={ticketMsg}
          defaultObjectId={activeRoom?.scopeObjectId ?? null}
          defaultObjectName={activeRoom?.scopeObjectName ?? null}
          onClose={() => setTicketMsg(null)}
          onDone={(num) => {
            setTicketMsg(null)
            toast.success(num ? `Заявка №${num} создана` : 'Заявка создана')
            qc.invalidateQueries({ queryKey: ['chat-messages', selectedRoom] })
            qc.invalidateQueries({ queryKey: ['chat-rooms'] })
          }} />
      )}
      <CreateChatDialog open={createOpen} onOpenChange={setCreateOpen} scopeProduct={scope}
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
      {/* Список — тянется мышью: у кого-то длинные названия групп, у кого-то важнее
          ширина переписки. Ширина помнится между заходами (localStorage). */}
      <div className="flex shrink-0 flex-col border-r border-border/50" style={{ width: listWidth }}>{listView}</div>
      {/* Разделитель: полоса 4px, подсвечивается под курсором. */}
      <div role="separator" aria-orientation="vertical" title="Потяните, чтобы изменить ширину"
        onPointerDown={startResize}
        className="w-1 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-primary/40" />
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
