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
import { Camera, CornerDownLeft, Gauge, KeyRound, Loader2, LogOut, Monitor, Moon, Sparkles, Sun, Trash2, User } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import * as workService from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { changePassword, logoutAll } from '@/services/authService'
import {
  ВИДЫ_ПИСЕМ, ОШИБКА_ДНЯ, подписьПояса, порядокВидовПисем, поясаПоСмещению,
  ошибкаПароля, ошибкаФото, рабочийДеньВерен,
} from '@/lib/profileRules'

type Draft = {
  name: string
  /** Виды писем, которые человек согласен получать. */
  emailKinds: string[]
  mobile: string
  office: string
  tz: string
  workStart: string
  workEnd: string
  notify: string[]
  theme: ThemePreference
  level: UiLevel
  send: SendMode
  photo: File | null
  photoRemoved: boolean
}

/** Куда приходят уведомления о поручениях. Порядок — как на сервере
 *  (`notify.TASK_CHANNELS`), иначе сравнение черновика с профилем врёт. */
const КАНАЛЫ: { id: string; label: string; hint: string }[] = [
  { id: 'secretary', label: 'Чат «Секретарь»', hint: 'Там же, где напоминания и сводка дня.' },
  { id: 'notices', label: 'Чат «Уведомления»', hint: 'Отдельный канал только для поручений.' },
  { id: 'email', label: 'Почта', hint: 'Письмом на адрес, которым вы входите.' },
]
const КАНАЛЫ_ПО_УМОЛЧАНИЮ = ['secretary', 'email']
const порядокКаналов = (list: string[]) => КАНАЛЫ.map((k) => k.id).filter((id) => list.includes(id))

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

/** Помощники, ведущие мой календарь, и календари, которые веду я. */
function CalendarDelegates({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['calendar-delegates', companyId],
    queryFn: () => workService.calendarDelegates(companyId),
    enabled: !!companyId,
  })
  const people = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })
  const обновить = () =>
    qc.invalidateQueries({ queryKey: ['calendar-delegates', companyId] })

  const добавить = useMutation({
    mutationFn: (userId: string) => workService.addCalendarDelegate(companyId, userId),
    onSuccess: () => { toast.success('Полномочие выдано'); void обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не выдалось'),
  })
  const отозвать = useMutation({
    mutationFn: (id: string) => workService.revokeCalendarDelegate(companyId, id),
    onSuccess: () => { toast.success('Полномочие забрано'); void обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не отозвалось'),
  })

  const мои = q.data?.mine ?? []
  const чужие = q.data?.for_others ?? []

  return (
    <div className="space-y-2">
      {мои.map((d) => (
        <div key={d.id} className="flex items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate">{d.name}</span>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
            disabled={отозвать.isPending}
            onClick={() => {
              if (window.confirm(`Забрать полномочие у ${d.name}? Встречи останутся, вести ваш календарь он больше не сможет.`)) {
                отозвать.mutate(d.id)
              }
            }}>
            Забрать
          </Button>
        </div>
      ))}
      <SearchPicker
        items={(people.data?.people ?? []).map((p) => ({
          id: p.id, name: p.name, party: p.partyType }))}
        value="" onChange={(id) => добавить.mutate(id)}
        placeholder="Доверить помощнику" searchPlaceholder="Фамилия или имя…"
        className="w-full" loading={people.isLoading} />
      {чужие.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Вы ведёте календарь: {чужие.map((d) => d.name).join(', ')}
        </p>
      )}
    </div>
  )
}

/** Сегменты выбора — один язык на все настройки страницы.
 *  Это выбор одного из нескольких, поэтому группа объявлена радиогруппой:
 *  обычные кнопки не сообщают незрячему, что именно выбрано. */
function Segments<T extends string>({ value, onChange, options, label }: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; icon: typeof Sun; hint: string }[]
  label: string
}) {
  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border p-0.5">
        {options.map((o) => {
          const I = o.icon
          const active = o.value === value
          return (
            <button key={o.value} type="button" role="radio" aria-checked={active}
              onClick={() => onChange(o.value)}
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

/**
 * Смена пароля изнутри сеанса.
 *
 * До этого пароль можно было поменять только через «забыли пароль» — то есть
 * выйти и пойти в почту, имея на руках рабочий вход. Пункт меню при этом
 * обещал «личные данные и пароль», а пароля на экране не было.
 *
 * Своя кнопка, а не общий «Сохранить»: пароль фиксируется отдельным действием
 * и отдельным подтверждением, и смешивать его с черновиком телефонов нельзя.
 */
function PasswordBlock() {
  const [текущий, setТекущий] = useState('')
  const [новый, setНовый] = useState('')
  const [повтор, setПовтор] = useState('')
  const [занят, setЗанят] = useState(false)
  const тронуто = !!(текущий || новый || повтор)
  const ошибка = тронуто ? ошибкаПароля(текущий, новый, повтор) : null

  async function сменить() {
    const беда = ошибкаПароля(текущий, новый, повтор)
    if (беда) { toast.error(беда); return }
    setЗанят(true)
    try {
      await changePassword(текущий, новый)
      setТекущий(''); setНовый(''); setПовтор('')
      toast.success('Пароль изменён', {
        description: 'На других устройствах придётся войти заново — здесь вход сохранён.',
      })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сменить пароль')
    } finally {
      setЗанят(false)
    }
  }

  async function выйтиВезде() {
    if (!window.confirm('Выйти на всех устройствах? Входить придётся заново везде, включая это окно.')) return
    try { await logoutAll() } catch { /* токен уже снят */ }
    window.location.assign('/login')
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="pers-pass-cur" className="text-xs font-normal text-muted-foreground">
            Текущий пароль
          </Label>
          <Input id="pers-pass-cur" type="password" autoComplete="current-password"
            value={текущий} onChange={(e) => setТекущий(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pers-pass-new" className="text-xs font-normal text-muted-foreground">
            Новый пароль
          </Label>
          <Input id="pers-pass-new" type="password" autoComplete="new-password"
            value={новый} onChange={(e) => setНовый(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pers-pass-rep" className="text-xs font-normal text-muted-foreground">
            Ещё раз новый
          </Label>
          <Input id="pers-pass-rep" type="password" autoComplete="new-password"
            value={повтор} onChange={(e) => setПовтор(e.target.value)} />
        </div>
      </div>
      {ошибка && <p className="text-xs text-destructive">{ошибка}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" disabled={!!ошибка || !тронуто || занят}
          onClick={() => void сменить()}>
          {занят && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          <KeyRound className="mr-1.5 h-3.5 w-3.5" />
          Сменить пароль
        </Button>
        <Button type="button" variant="ghost" size="sm" className="text-destructive"
          onClick={() => void выйтиВезде()}>
          <LogOut className="mr-1.5 h-3.5 w-3.5" />
          Выйти на всех устройствах
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Смена пароля гасит вход на других устройствах; это окно остаётся рабочим.
        Если пароль мог утечь — сначала смените его, затем выйдите везде.
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
    tz: user?.tz ?? 'Europe/Moscow',
    workStart: user?.work_start ?? '09:00',
    workEnd: user?.work_end ?? '18:00',
    notify: порядокКаналов(user?.task_notify ?? КАНАЛЫ_ПО_УМОЛЧАНИЮ),
    emailKinds: порядокВидовПисем(user?.email_notify ?? ВИДЫ_ПИСЕМ.map((k) => k.id)),
    theme: themePref,
    level,
    send: sendMode,
    photo: null,
    photoRemoved: false,
  })
  const [draft, setDraft] = useState<Draft>(исходный)
  const [preview, setPreview] = useState<string | null>(null)

  // Профиль приезжает асинхронно, а черновик собирается при первом рендере —
  // до его прихода в нём стоят умолчания. Пока человек ничего не трогал,
  // пересобираем черновик на пришедшем профиле: иначе он видит чужие значения
  // и сохраняет их поверх своих (раньше так терялось имя, теперь — ещё и
  // пояс, телефоны и выбор писем).
  const [тронут, setТронут] = useState(false)
  useEffect(() => {
    // Только когда профиль есть: во время перезапроса контекст на миг отдаёт
    // null, и пересборка по нему вернула бы в форму умолчания — ровно то, что
    // этот эффект и должен предотвращать.
    if (!тронут && user) setDraft(исходный())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [тронут, user?.id, user?.name, user?.phone_mobile, user?.phone_office, user?.tz,
      user?.work_start, user?.work_end,
      (user?.task_notify ?? []).join(), (user?.email_notify ?? []).join()])

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setТронут(true)
    setDraft((d) => ({ ...d, [k]: v }))
  }

  const dirty = draft.name.trim() !== (user?.name ?? '')
    || draft.mobile.trim() !== (user?.phone_mobile ?? '')
    || draft.office.trim() !== (user?.phone_office ?? '')
    || draft.tz !== (user?.tz ?? 'Europe/Moscow')
    || draft.workStart !== (user?.work_start ?? '09:00')
    || draft.workEnd !== (user?.work_end ?? '18:00')
    || draft.notify.join() !== порядокКаналов(user?.task_notify ?? КАНАЛЫ_ПО_УМОЛЧАНИЮ).join()
    || draft.emailKinds.join() !== порядокВидовПисем(user?.email_notify ?? ВИДЫ_ПИСЕМ.map((k) => k.id)).join()
    || draft.theme !== themePref || draft.level !== level || draft.send !== sendMode
    || !!draft.photo || draft.photoRemoved

  function отменить() {
    if (preview) URL.revokeObjectURL(preview)
    setPreview(null)
    setDraft(исходный())
    setТронут(false)
  }

  function выбратьФайл(file: File | null) {
    if (!file) return
    const бедаФото = ошибкаФото(file)
    if (бедаФото) { toast.error(бедаФото); return }
    if (preview) URL.revokeObjectURL(preview)
    setPreview(URL.createObjectURL(file))
    setТронут(true)
    setDraft((d) => ({ ...d, photo: file, photoRemoved: false }))
  }

  async function сохранить() {
    const имя = draft.name.trim()
    if (имя.length < 2) { toast.error('Имя слишком короткое'); return }
    if (!рабочийДеньВерен(draft.workStart, draft.workEnd)) { toast.error(ОШИБКА_ДНЯ); return }
    setSaving(true)
    try {
      // Сначала серверное — если оно не пройдёт, локальные настройки не должны
      // разъехаться с тем, что человек видит на других устройствах.
      const тело: {
        name?: string; avatarUrl?: string; phoneMobile?: string; phoneOffice?: string
        tz?: string; workStart?: string; workEnd?: string; taskNotify?: string[]
        emailNotify?: string[]
      } = {}
      if (имя !== (user?.name ?? '')) тело.name = имя
      if (draft.mobile.trim() !== (user?.phone_mobile ?? '')) тело.phoneMobile = draft.mobile.trim()
      if (draft.office.trim() !== (user?.phone_office ?? '')) тело.phoneOffice = draft.office.trim()
      if (draft.tz !== (user?.tz ?? 'Europe/Moscow')) тело.tz = draft.tz
      if (draft.workStart !== (user?.work_start ?? '09:00')) тело.workStart = draft.workStart
      if (draft.workEnd !== (user?.work_end ?? '18:00')) тело.workEnd = draft.workEnd
      if (draft.notify.join() !== порядокКаналов(user?.task_notify ?? КАНАЛЫ_ПО_УМОЛЧАНИЮ).join()) {
        тело.taskNotify = draft.notify
      }
      if (draft.emailKinds.join() !== порядокВидовПисем(user?.email_notify ?? ВИДЫ_ПИСЕМ.map((k) => k.id)).join()) {
        тело.emailNotify = draft.emailKinds
      }
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
      setТронут(false)
      toast.success('Настройки сохранены')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const деньВерен = рабочийДеньВерен(draft.workStart, draft.workEnd)
  const почтаВключена = draft.notify.includes('email')
  const фото = preview ?? (draft.photoRemoved ? null : user?.avatar_url ?? null)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <User className="h-5 w-5" />
          Личные настройки
        </CardTitle>
        <CardDescription>
          Ваш профиль и то, как ведёт себя интерфейс лично у вас. Имя, фото, связь,
          рабочее время и уведомления действуют во всех приложениях пространства и на
          любом устройстве; оформление, режим и способ отправки — настройки этого
          устройства. Фото видно везде, где вы появляетесь, — в чате, составе группы,
          обсуждении задачи.
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
                  onClick={() => { if (preview) URL.revokeObjectURL(preview); setPreview(null); setТронут(true); setDraft((d) => ({ ...d, photo: null, photoRemoved: true })) }}>
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  Убрать
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Связь — как с человеком связаться помимо пространства */}
        <div id="profile-contacts" className="scroll-mt-24 space-y-3 border-t pt-5">
          <div>
            <Label>Связь</Label>
            <p className="text-xs text-muted-foreground">
              Эти сведения видят участники пространства, когда нужно с вами связаться
              напрямую. Заполняете вы сами.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <span className="block text-xs font-normal text-muted-foreground">
                Электронная почта
              </span>
              <p id="pers-mail" className="flex h-9 items-center text-sm font-medium">
                {user?.email || '—'}
              </p>
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

        {/* Доступ к учётной записи. Стоит сразу за почтой: почта — это логин,
            и пароль человек ищет рядом с ним, а не в конце страницы. */}
        <div id="profile-security" className="scroll-mt-24 space-y-3 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Безопасность</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Пароль от входа в пространство. Меняется здесь — выходить и ждать
              письмо для этого не нужно.
            </p>
          </div>
          <PasswordBlock />
        </div>

        {/* Когда человека можно трогать. Настройка не косметическая: по ней
            планировщик решает, доставить регламентное сейчас или сдвинуть на
            утро. Пространство растянуто от Владивостока до Москвы, и «за сутки
            до срока» не бывает срочнее сна. */}
        <div id="profile-worktime" className="scroll-mt-24 space-y-3 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Рабочее время</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Сводка «Секретаря» приходит в начале дня и в середине, в вашем поясе.
              Вне этих часов и по выходным регламентные напоминания ждут: они не
              теряются, а сдвигаются на ближайшее рабочее окно. То, что вы поставили
              себе сами, приходит точно в срок и в тишину.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5 sm:col-span-3">
              <Label htmlFor="pers-tz" className="text-xs font-normal text-muted-foreground">
                Часовой пояс
              </Label>
              <select id="pers-tz" value={draft.tz}
                onChange={(e) => set('tz', e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm">
                {поясаПоСмещению().map(({ offset, зоны }) => (
                  <optgroup key={offset} label={`UTC+${offset}`}>
                    {зоны.map((z) => (
                      <option key={z.id} value={z.id}>{подписьПояса(z)}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pers-ws" className="text-xs font-normal text-muted-foreground">
                Начало дня
              </Label>
              <Input id="pers-ws" type="time" value={draft.workStart}
                onChange={(e) => set('workStart', e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pers-we" className="text-xs font-normal text-muted-foreground">
                Конец дня
              </Label>
              <Input id="pers-we" type="time" value={draft.workEnd}
                aria-invalid={!деньВерен} onChange={(e) => set('workEnd', e.target.value)} />
            </div>
          </div>
          {!деньВерен && <p className="text-xs text-destructive">{ОШИБКА_ДНЯ}</p>}
        </div>

        {/* Канал поручений выбирает сам человек: кто-то живёт в чате, кто-то в почте.
            Снять все галочки нельзя — поручение тогда не дошло бы никуда. */}
        <div id="profile-notifications" className="scroll-mt-24 space-y-3 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Уведомления о поручениях</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Куда сообщать, когда вам поручили задачу, передали её, упомянули вас или
              ответили по задаче. Можно выбрать несколько.
            </p>
          </div>
          <div className="space-y-2">
            {КАНАЛЫ.map((k) => {
              const on = draft.notify.includes(k.id)
              const last = on && draft.notify.length === 1
              return (
                <label key={k.id} className={cn('flex items-start gap-2 text-sm', last ? 'cursor-default' : 'cursor-pointer')}>
                  <Checkbox className="mt-0.5" checked={on} disabled={last}
                    title={last ? 'Нужен хотя бы один канал' : undefined}
                    onCheckedChange={(v) => set('notify', порядокКаналов(
                      v === true ? [...draft.notify, k.id] : draft.notify.filter((x) => x !== k.id)))} />
                  <span>
                    {k.label}
                    <span className="block text-xs text-muted-foreground">{k.hint}</span>
                  </span>
                </label>
              )
            })}
          </div>
        </div>

        {/* Что из этого уходит письмом. Канал «Почта» выше отвечает на вопрос
            «писать ли вообще», а здесь человек выбирает, о чём именно: раньше
            поток ответов по чужим задачам лечился только полным отключением
            почты — вместе с «вам поручено». Сводка дня живёт здесь же: для
            человека это такое же письмо в его ящик, а не отдельная подписка. */}
        <div id="profile-email" className="scroll-mt-24 space-y-3 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Что присылать на почту</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {почтаВключена
                ? <>Письма уходят на {user?.email || 'вашу почту'}. Снимите всё — почта замолчит, уведомления останутся в чате.</>
                : <>Канал «Почта» выключен выше — письма не уходят. Включите его, чтобы выбрать, о чём писать.</>}
            </p>
          </div>
          <div className="space-y-2">
            {ВИДЫ_ПИСЕМ.map((k) => {
              const on = draft.emailKinds.includes(k.id)
              return (
                <label key={k.id}
                  className={cn('flex items-start gap-2 text-sm',
                    почтаВключена ? 'cursor-pointer' : 'cursor-default opacity-60')}>
                  <Checkbox className="mt-0.5" checked={on} disabled={!почтаВключена}
                    onCheckedChange={(v) => set('emailKinds', порядокВидовПисем(
                      v === true ? [...draft.emailKinds, k.id] : draft.emailKinds.filter((x) => x !== k.id)))} />
                  <span>
                    {k.label}
                    <span className="block text-xs text-muted-foreground">{k.hint}</span>
                  </span>
                </label>
              )
            })}
          </div>
          {почтаВключена && draft.emailKinds.length === 0 && (
            <p className="text-xs text-amber-600 dark:text-amber-500">
              На почту не уйдёт ничего. Поручения вы по-прежнему увидите в выбранных чатах.
            </p>
          )}
        </div>

        {/* Кто вправе вести мой календарь. Полномочие выдаёт ТОЛЬКО владелец —
            ни администратор, ни сам помощник: иначе «ведение календаря» стало бы
            способом получить доступ без ведома того, чей он. Это именно
            полномочие, а не доступ к учётной записи: помощник действует от
            своего имени, и в журнале видно обоих. */}
        <div className="space-y-3 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Кто ведёт мой календарь</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Помощник сможет собирать, переносить и отменять ваши встречи и звать
              участников — от своего имени, с пометкой «от имени вас». Почты,
              документов и записной книжки это не открывает. Полномочие выдаётся и
              забирается сразу, без кнопки «Сохранить».
            </p>
          </div>
          <CalendarDelegates companyId={company.id} />
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
        <div id="profile-appearance" className="scroll-mt-24 space-y-2 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Настройки этого устройства</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Оформление, режим и способ отправки хранятся в этом браузере. На другом
              компьютере или телефоне их нужно выбрать заново.
            </p>
          </div>
          <Label>Оформление</Label>
          <Segments label="Оформление" value={draft.theme} onChange={(v) => set('theme', v)} options={[
            { value: 'light', label: 'Светлая', icon: Sun, hint: 'Всегда светлый экран.' },
            { value: 'dark', label: 'Тёмная', icon: Moon, hint: 'Всегда тёмный экран.' },
            { value: 'system', label: 'Как в системе', icon: Monitor, hint: 'Следовать настройке устройства — светлая днём, тёмная вечером, если так настроена система.' },
          ]} />
        </div>

        {/* Режим работы */}
        <div className="space-y-2">
          <Label>Режим работы</Label>
          <Segments label="Режим работы" value={draft.level} onChange={(v) => set('level', v)} options={[
            { value: 'simple', label: 'Простой', icon: Gauge, hint: 'На экранах остаётся то, что нужно каждый день. Ничего не отключается: где что-то убрано, видно, сколько именно и как открыть.' },
            { value: 'advanced', label: 'Все функции', icon: Sparkles, hint: 'Показывать всё сразу, включая редкие разделы и настройки.' },
          ]} />
        </div>

        {/* Отправка сообщений */}
        <div className="space-y-2">
          <Label>Отправка сообщений</Label>
          <Segments label="Отправка сообщений" value={draft.send} onChange={(v) => set('send', v)} options={[
            { value: 'enter', label: 'По Enter', icon: CornerDownLeft, hint: 'Enter отправляет, Shift+Enter переносит строку. Быстро для коротких реплик.' },
            { value: 'ctrlEnter', label: 'По Ctrl+Enter', icon: CornerDownLeft, hint: 'Enter переносит строку, отправляет Ctrl+Enter или кнопка. Удобно, когда пишете абзацами.' },
          ]} />
          <p className="text-xs text-muted-foreground">
            Действует в чате, при правке отправленного и в обсуждении задачи.
            Ctrl+Enter отправляет в любом случае.
          </p>
        </div>

        {/* Фиксация. Пока есть несохранённое — строка держится у нижнего края
            окна: иначе человек правит телефон вверху, а кнопка ждёт его через
            два экрана прокрутки. */}
        <div className={cn('flex items-center gap-2 border-t pt-4',
          dirty && 'sticky bottom-0 -mx-6 -mb-6 border-t bg-background/95 px-6 pb-4 backdrop-blur')}>
          <Button type="button" aria-label="Сохранить личные настройки"
            onClick={сохранить} disabled={!dirty || saving || !деньВерен}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Сохранить
          </Button>
          <Button type="button" variant="ghost" aria-label="Отменить изменения личных настроек"
            onClick={отменить} disabled={!dirty || saving}>
            Отменить
          </Button>
          {dirty && !saving && (
            <span className="text-xs text-muted-foreground">
              {деньВерен ? 'Есть несохранённые изменения' : ОШИБКА_ДНЯ}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
