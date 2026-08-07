/**
 * Личные настройки — то, что человек выбирает для себя, а не для компании.
 *
 * Почему отдельной страницей, а не переключателями в меню профиля: меню
 * закрывается после каждого щелчка, и настройка в нём превращается в игру
 * «попади в пункт и открой меню заново». Здесь всё видно разом, изменения
 * копятся в черновике, и человек их ФИКСИРУЕТ — «Сохранить» либо «Отменить».
 * Пока не сохранил, ничего не применилось: тема не мигает, режим не съезжает.
 *
 * Фото — исключение по механике, но не по правилу: файл выбирается сразу и
 * показывается превью, а на сервер уходит тем же «Сохранить».
 */
import { useEffect, useRef, useState } from 'react'
import { Camera, CornerDownLeft, Gauge, Loader2, Monitor, Moon, Sparkles, Sun, Trash2, User } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useTheme, type ThemePreference } from '@/hooks/useTheme'
import { useUiLevel, type UiLevel } from '@/hooks/useUiLevel'
import { useSendMode, type SendMode } from '@/hooks/useSendMode'
import * as chat from '@/services/chatService'

type Draft = {
  name: string
  mobile: string
  office: string
  theme: ThemePreference
  level: UiLevel
  send: SendMode
  photo: File | null
  photoRemoved: boolean
}

/** Кем человек приходится этому пространству. Заполняет администратор. */
const УЧАСТИЕ: Record<string, { label: string; hint: string }> = {
  internal: {
    label: 'Сотрудник организации',
    hint: 'Полноценный участник компании, которой принадлежит пространство.',
  },
  partner: {
    label: 'Внешний участник',
    hint: 'Сотрудник другой компании — подрядчик, поставщик, заказчик. Видит то, что ему открыли.',
  },
  vendor: {
    label: 'Поддержка платформы',
    hint: 'Канал помощи по самой платформе: особый статус, свои права и доступы.',
  },
}

/** Сегменты выбора — один язык на все настройки страницы. */
function Segments<T extends string>({ value, onChange, options }: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; icon: typeof Sun; hint: string }[]
}) {
  return (
    <div className="space-y-2">
      <div className="inline-flex rounded-lg border p-0.5">
        {options.map((o) => {
          const I = o.icon
          const active = o.value === value
          return (
            <button key={o.value} type="button" onClick={() => onChange(o.value)}
              className={cn('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
                active ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}>
              <I className="h-4 w-4" />
              {o.label}
            </button>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        {options.find((o) => o.value === value)?.hint}
      </p>
    </div>
  )
}

export function PersonalSettings() {
  const { user, refreshMe } = useAuth()
  const { company } = useCompany()
  const { preference: themePref, setTheme } = useTheme()
  const { level, setLevel } = useUiLevel()
  const { mode: sendMode, setMode: setSendMode } = useSendMode()
  const fileRef = useRef<HTMLInputElement>(null)
  const [saving, setSaving] = useState(false)

  const исходный = (): Draft => ({
    name: user?.name ?? '',
    mobile: user?.phone_mobile ?? '',
    office: user?.phone_office ?? '',
    theme: themePref,
    level,
    send: sendMode,
    photo: null,
    photoRemoved: false,
  })
  const [draft, setDraft] = useState<Draft>(исходный)
  const [preview, setPreview] = useState<string | null>(null)

  // Профиль приезжает асинхронно: пока его нет, в поле имени пусто, и черновик
  // нужно пересобрать, иначе человек сохранит пустое имя поверх своего.
  useEffect(() => {
    setDraft((d) => (d.name === '' && user?.name ? { ...d, name: user.name } : d))
  }, [user?.name])

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  const dirty = draft.name.trim() !== (user?.name ?? '')
    || draft.mobile.trim() !== (user?.phone_mobile ?? '')
    || draft.office.trim() !== (user?.phone_office ?? '')
    || draft.theme !== themePref || draft.level !== level || draft.send !== sendMode
    || !!draft.photo || draft.photoRemoved

  function отменить() {
    if (preview) URL.revokeObjectURL(preview)
    setPreview(null)
    setDraft(исходный())
  }

  function выбратьФайл(file: File | null) {
    if (!file) return
    if (!file.type.startsWith('image/')) { toast.error('Нужна картинка'); return }
    if (preview) URL.revokeObjectURL(preview)
    setPreview(URL.createObjectURL(file))
    setDraft((d) => ({ ...d, photo: file, photoRemoved: false }))
  }

  async function сохранить() {
    const имя = draft.name.trim()
    if (имя.length < 2) { toast.error('Имя слишком короткое'); return }
    setSaving(true)
    try {
      // Сначала серверное — если оно не пройдёт, локальные настройки не должны
      // разъехаться с тем, что человек видит на других устройствах.
      const тело: { name?: string; avatarUrl?: string; phoneMobile?: string; phoneOffice?: string } = {}
      if (имя !== (user?.name ?? '')) тело.name = имя
      if (draft.mobile.trim() !== (user?.phone_mobile ?? '')) тело.phoneMobile = draft.mobile.trim()
      if (draft.office.trim() !== (user?.phone_office ?? '')) тело.phoneOffice = draft.office.trim()
      if (draft.photoRemoved) тело.avatarUrl = ''
      else if (draft.photo) тело.avatarUrl = (await chat.uploadAttachment(draft.photo, company.id)).fileUrl
      if (Object.keys(тело).length) {
        await chat.updateMe(тело)
        await refreshMe()
      }
      if (draft.theme !== themePref) setTheme(draft.theme)
      if (draft.level !== level) setLevel(draft.level)
      if (draft.send !== sendMode) setSendMode(draft.send)
      if (preview) URL.revokeObjectURL(preview)
      setPreview(null)
      setDraft((d) => ({ ...d, photo: null, photoRemoved: false }))
      toast.success('Настройки сохранены')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const фото = preview ?? (draft.photoRemoved ? null : user?.avatar_url ?? null)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <User className="h-5 w-5" />
          Личные настройки
        </CardTitle>
        <CardDescription>
          Ваш профиль и то, как ведёт себя интерфейс лично у вас. Настройки
          действуют во всех приложениях пространства; фото видно везде, где вы
          появляетесь, — в чате, составе группы, обсуждении задачи.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Фото и имя */}
        <div className="flex items-start gap-4">
          <input ref={fileRef} type="file" accept="image/*" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0] ?? null; e.target.value = ''; выбратьФайл(f) }} />
          <button type="button" onClick={() => fileRef.current?.click()}
            className="relative size-16 shrink-0 overflow-hidden rounded-2xl bg-primary/10 ring-1 ring-border"
            title="Выбрать фото">
            {фото
              ? <img src={фото} alt="" className="h-full w-full object-cover" />
              : <User className="absolute inset-0 m-auto size-7 text-muted-foreground" />}
          </button>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="space-y-1.5">
              <Label htmlFor="pers-name">Имя</Label>
              <Input id="pers-name" value={draft.name} maxLength={255}
                onChange={(e) => set('name', e.target.value)}
                placeholder="Фамилия Имя Отчество" />
              <p className="text-xs text-muted-foreground">
                Так вас видят в чатах и задачах; этим же именем подписаны ваши документы.
              </p>
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Camera className="mr-1.5 h-3.5 w-3.5" />
                {фото ? 'Другое фото' : 'Добавить фото'}
              </Button>
              {фото && (
                <Button type="button" variant="ghost" size="sm"
                  onClick={() => { if (preview) URL.revokeObjectURL(preview); setPreview(null); setDraft((d) => ({ ...d, photo: null, photoRemoved: true })) }}>
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  Убрать
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Связь — как с человеком связаться помимо пространства */}
        <div className="space-y-3 border-t pt-5">
          <div>
            <Label>Связь</Label>
            <p className="text-xs text-muted-foreground">
              Эти сведения видят участники пространства, когда нужно с вами связаться
              напрямую. Заполняете вы сами.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="pers-mail" className="text-xs font-normal text-muted-foreground">
                Электронная почта
              </Label>
              <Input id="pers-mail" value={user?.email ?? ''} readOnly disabled />
              <p className="text-[11px] text-muted-foreground">Ею же вы входите — меняет администратор.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pers-mob" className="text-xs font-normal text-muted-foreground">
                Мобильный
              </Label>
              <Input id="pers-mob" value={draft.mobile} maxLength={40} inputMode="tel"
                onChange={(e) => set('mobile', e.target.value)} placeholder="+7 900 000-00-00" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pers-off" className="text-xs font-normal text-muted-foreground">
                Городской
              </Label>
              <Input id="pers-off" value={draft.office} maxLength={40} inputMode="tel"
                onChange={(e) => set('office', e.target.value)} placeholder="+7 812 000-00-00, доб. 123" />
            </div>
          </div>
        </div>

        {/* Место в пространстве — сведения администратора, не личное дело */}
        <div className="space-y-3 border-t pt-5">
          <div>
            <Label>Место в пространстве</Label>
            <p className="text-xs text-muted-foreground">
              Кем вы здесь являетесь и что вам открыто. Эти сведения ведёт
              администратор пространства — если что-то указано неверно, обратитесь к нему.
            </p>
          </div>
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">Компания</dt>
              <dd className="mt-0.5">{user?.company_name || company.name || '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Должность</dt>
              <dd className="mt-0.5">{user?.position || <span className="text-muted-foreground">не указана</span>}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Кто вы здесь</dt>
              <dd className="mt-0.5">
                {УЧАСТИЕ[user?.party_type ?? 'internal']?.label ?? 'Участник'}
                {user?.party_org && <span className="text-muted-foreground"> · {user.party_org}</span>}
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {УЧАСТИЕ[user?.party_type ?? 'internal']?.hint}
                </p>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Роль</dt>
              <dd className="mt-0.5">
                {user?.is_superadmin ? 'Суперадминистратор'
                  : user?.company_role === 'admin' ? 'Администратор пространства' : 'Сотрудник'}
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  Роль решает, что вам доступно: администратор ведёт состав людей и
                  настройки пространства.
                </p>
              </dd>
            </div>
          </dl>
        </div>

        {/* Оформление */}
        <div className="space-y-2 border-t pt-5">
          <Label>Оформление</Label>
          <Segments value={draft.theme} onChange={(v) => set('theme', v)} options={[
            { value: 'light', label: 'Светлая', icon: Sun, hint: 'Всегда светлый экран.' },
            { value: 'dark', label: 'Тёмная', icon: Moon, hint: 'Всегда тёмный экран.' },
            { value: 'system', label: 'Как в системе', icon: Monitor, hint: 'Следовать настройке устройства — светлая днём, тёмная вечером, если так настроена система.' },
          ]} />
        </div>

        {/* Режим работы */}
        <div className="space-y-2">
          <Label>Режим работы</Label>
          <Segments value={draft.level} onChange={(v) => set('level', v)} options={[
            { value: 'simple', label: 'Простой', icon: Gauge, hint: 'На экранах остаётся то, что нужно каждый день. Ничего не отключается: где что-то убрано, видно, сколько именно и как открыть.' },
            { value: 'advanced', label: 'Все функции', icon: Sparkles, hint: 'Показывать всё сразу, включая редкие разделы и настройки.' },
          ]} />
        </div>

        {/* Отправка сообщений */}
        <div className="space-y-2">
          <Label>Отправка сообщений</Label>
          <Segments value={draft.send} onChange={(v) => set('send', v)} options={[
            { value: 'enter', label: 'По Enter', icon: CornerDownLeft, hint: 'Enter отправляет, Shift+Enter переносит строку. Быстро для коротких реплик.' },
            { value: 'ctrlEnter', label: 'По Ctrl+Enter', icon: CornerDownLeft, hint: 'Enter переносит строку, отправляет Ctrl+Enter или кнопка. Удобно, когда пишете абзацами.' },
          ]} />
          <p className="text-xs text-muted-foreground">
            Действует в чате, при правке отправленного и в обсуждении задачи.
            Ctrl+Enter отправляет в любом случае.
          </p>
        </div>

        {/* Фиксация */}
        <div className="flex items-center gap-2 border-t pt-4">
          <Button type="button" onClick={сохранить} disabled={!dirty || saving}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Сохранить
          </Button>
          <Button type="button" variant="ghost" onClick={отменить} disabled={!dirty || saving}>
            Отменить
          </Button>
          {dirty && !saving && (
            <span className="text-xs text-muted-foreground">Есть несохранённые изменения</span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
