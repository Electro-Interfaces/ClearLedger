/**
 * «Звуки» — что слышит звонящий и где: приветствие, объявление очереди, предложение
 * перезвонить, сообщения вне часов и запасного сценария.
 *
 * Сверху — места, где звучат звуки, и что там сейчас; привязка меняет черновик правил
 * приёма и начинает звучать только после его проверки и применения (на экране «Правила
 * приёма»): так звук на живой линии не сменится случайным нажатием. Ниже — библиотека:
 * свои записи (загрузка, прослушивание, замена, удаление) и стандартные звуки Asterisk,
 * на которые ссылаются правила. Узел сам приводит файл к 8 кГц моно — формату Asterisk.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Music, Pencil, Play, Square, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { ктоСделал, когда, объём, сек } from './format'
import { Heading, NodeError } from './parts'

const ПРЕДЕЛ_БАЙТ = 10 * 1024 * 1024
const ПРЕДЕЛ_СЕК = 300
const ИМЯ = /^[a-z0-9][a-z0-9_-]{0,63}$/

/** Имя звука из имени файла: латиница, цифры, `-` и `_`, как требует узел. */
function имяИзФайла(файл: string) {
  const база = файл.replace(/\.[^.]+$/, '').toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 64)
  return ИМЯ.test(база) ? база : ''
}

/** Длительность файла по данным браузера; не разобрал — `null`, тогда решит узел. */
function длительность(файл: File): Promise<number | null> {
  return new Promise(resolve => {
    const url = URL.createObjectURL(файл)
    const a = new Audio()
    const конец = (v: number | null) => { URL.revokeObjectURL(url); resolve(v) }
    a.preload = 'metadata'
    a.onloadedmetadata = () => конец(Number.isFinite(a.duration) ? a.duration : null)
    a.onerror = () => конец(null)
    a.src = url
  })
}

/** Где используется: `reception@3` → «действующие правила r3». */
function гдеИспользуется(u: string) {
  const [вид, версия] = u.split('@')
  const что = вид === 'reception' ? 'правила приёма' : вид
  return версия === 'draft' ? `черновик: ${что}` : `${что} r${версия}`
}

export default function VoiceSoundsPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const звуки = useQuery({ queryKey: ['voice-sounds', companyId], queryFn: () => voice.sounds(companyId) })
  const места = useQuery({ queryKey: ['voice-sound-places', companyId], queryFn: () => voice.soundPlaces(companyId) })
  const [замена, setЗамена] = useState<voice.Sound | null>(null)
  const обновить = () => Promise.all([
    qc.invalidateQueries({ queryKey: ['voice-sounds', companyId] }),
    qc.invalidateQueries({ queryKey: ['voice-sound-places', companyId] }),
  ])

  const все = звуки.data?.items ?? []
  const свои = все.filter(s => !s.standard)
  const стандартные = все.filter(s => s.standard)

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Звуки"
        подпись="Что слышит звонящий: приветствие, ожидание, предложение перезвонить, сообщения вне часов. Свои записи и стандартные звуки Asterisk." />

      <section aria-label="Где звучит" className="space-y-2 rounded-xl border border-border bg-card p-4">
        <h2 className="font-headline text-base font-semibold">Где звучит</h2>
        <p className="text-xs text-muted-foreground">
          Смена звука — правка черновика правил приёма. Звонящий услышит новый звук после того,
          как черновик проверят и применят на экране <Link to="/voice/reception" className="text-primary underline-offset-2 hover:underline">«Правила приёма»</Link>.
        </p>
        {места.isLoading && <p role="status" className="text-sm">Читаем места у узла…</p>}
        {места.isError && <NodeError ошибка={места.error} что="прочитать, где звучат звуки" />}
        {места.data?.draft && (
          <p className="rounded-lg border border-primary/30 bg-primary/5 p-2 text-sm">
            Есть черновик правил приёма r{места.data.draft.version}: звуки, отмеченные «в черновике», ещё не звучат.
          </p>
        )}
        {места.data && (
          <ul className="divide-y divide-border/60">
            {места.data.items.map(м => (
              <PlaceRow key={м.place} м={м} звуки={все} onDone={обновить} />
            ))}
          </ul>
        )}
      </section>

      <UploadForm замена={замена} onDone={async () => { setЗамена(null); await обновить() }} onCancel={() => setЗамена(null)} />

      <section aria-label="Свои записи" className="space-y-2">
        <h2 className="font-headline text-base font-semibold">Свои записи</h2>
        {звуки.isLoading && <p role="status" className="text-sm">Читаем звуки у узла…</p>}
        {звуки.isError && <NodeError ошибка={звуки.error} что="прочитать звуки" />}
        {звуки.isSuccess && !свои.length && (
          <EmptyBlock иконка={Music} текст="Своих записей пока нет"
            подсказка="Загрузите приветствие или сообщение вне часов: WAV, MP3 или OGG до 10 МБ и 5 минут." />
        )}
        {!!свои.length && (
          <ul className="space-y-2">
            {свои.map(s => <SoundRow key={s.name} s={s} onReplace={() => setЗамена(s)} onDone={обновить} />)}
          </ul>
        )}
      </section>

      {!!стандартные.length && (
        <details className="rounded-xl border border-border bg-card p-4">
          <summary className="cursor-pointer text-sm font-medium">Стандартные звуки Asterisk ({стандартные.length})</summary>
          <p className="pt-2 text-xs text-muted-foreground">
            Звуки из поставки Asterisk, на которые ссылаются правила. На стенде они английские: для линии заказчика их стоит заменить своими записями.
          </p>
          <ul className="space-y-2 pt-2">
            {стандартные.map(s => <SoundRow key={s.ref} s={s} onDone={обновить} />)}
          </ul>
        </details>
      )}
    </div>
  )
}

/** Подпись звука в местах: своё название, иначе имя или ссылка. */
function подписьЗвука(v: string, звуки: voice.Sound[]) {
  const s = звуки.find(x => x.name === v || x.ref === v)
  if (!s) return v
  return s.title || s.name
}

function PlaceRow({ м, звуки, onDone }: { м: voice.SoundPlaceRow; звуки: voice.Sound[]; onDone: () => Promise<unknown> }) {
  const { companyId } = useCompany()
  const [правка, setПравка] = useState<string[] | null>(null)
  const [идёт, setИдёт] = useState(false)
  const вЧерновике = м.draft && м.draft.join('|') !== м.sounds.join('|')
  const обязателен = м.place === 'after_hours' || м.place === 'fallback'

  async function сохранить(список: string[]) {
    setИдёт(true)
    try {
      const ч = await voice.setSoundPlace(companyId, м.place, список)
      toast.success(`Записано в черновик правил приёма r${ч.version}. Зазвучит после проверки и применения.`)
      setПравка(null)
      await onDone()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Узел не принял правку')
    } finally {
      setИдёт(false)
    }
  }

  // Своё — по имени, стандартное — по ссылке `sound:…`: так их ждёт узел.
  const значение = (s: voice.Sound) => (s.standard ? s.ref : s.name)

  return (
    <li className="space-y-1.5 py-2.5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <p className="text-sm font-medium">{м.title}</p>
          <p className="text-sm">
            {м.sounds.length ? м.sounds.map(v => подписьЗвука(v, звуки)).join(', ')
              : <span className="text-muted-foreground">{м.place === 'agent_announce' ? 'короткий сигнал' : 'ничего не звучит'}</span>}
            {м.target && <span className="text-xs text-muted-foreground"> · цель {м.target}</span>}
          </p>
          {вЧерновике && (
            <p className="text-xs text-primary">
              в черновике: {м.draft!.length ? м.draft!.map(v => подписьЗвука(v, звуки)).join(', ') : 'без звука'}
            </p>
          )}
        </div>
        {!правка && (
          <Button variant="outline" size="sm" onClick={() => setПравка(м.draft ?? м.sounds)}><Pencil />Изменить</Button>
        )}
      </div>
      {правка && (
        <div className="space-y-2 rounded-lg border border-border p-3">
          <p className="text-xs text-muted-foreground">
            {м.multiple ? 'Можно несколько: звучат по порядку выбора.' : 'Один звук.'}
            {обязателен && ' Сообщение цели нельзя оставить без звука.'}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {звуки.map(s => {
              const v = значение(s)
              const выбран = правка.includes(v)
              return (
                <button key={v} type="button" aria-pressed={выбран}
                  onClick={() => setПравка(выбран ? правка.filter(x => x !== v) : м.multiple ? [...правка, v] : [v])}
                  className={cn('rounded-md border px-2 py-1 text-xs transition-colors',
                    выбран ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent/50')}>
                  {s.title || s.name}{s.standard && <span className="text-muted-foreground"> · стандартный</span>}
                </button>
              )
            })}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={идёт || (обязателен && !правка.length)} onClick={() => void сохранить(правка)}>
              {идёт ? 'Записываем…' : 'В черновик'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setПравка(null)}>Отмена</Button>
          </div>
        </div>
      )}
    </li>
  )
}

function SoundRow({ s, onReplace, onDone }: { s: voice.Sound; onReplace?: () => void; onDone: () => Promise<unknown> }) {
  const { companyId } = useCompany()
  const [звук, setЗвук] = useState<string | null>(null)
  const [удалить, setУдалить] = useState(false)
  const [идёт, setИдёт] = useState(false)
  const адрес = useRef<string | null>(null)
  // Адрес blob живёт, пока строка на экране: уходим — освобождаем память браузера.
  useEffect(() => () => { if (адрес.current) URL.revokeObjectURL(адрес.current) }, [])

  async function слушать() {
    if (звук) { setЗвук(null); return }
    try {
      if (!адрес.current) адрес.current = await voice.soundAudio(companyId, s.name)
      setЗвук(адрес.current)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Узел не отдал звук')
    }
  }

  async function удалитьЗвук() {
    setИдёт(true)
    try {
      await voice.deleteSound(companyId, s.name)
      toast.success(`Звук «${s.title || s.name}» удалён`)
      await onDone()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Звук не удалён')
      setУдалить(false)
    } finally {
      setИдёт(false)
    }
  }

  return (
    <li className="space-y-1.5 rounded-lg border border-border bg-card p-3 text-sm">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <p className="font-medium">{s.title || s.name}{s.standard && <span className="ml-2 rounded-md border border-border px-1.5 text-xs font-normal text-muted-foreground">стандартный</span>}</p>
          <p className="break-all font-mono text-xs text-muted-foreground">{s.ref}</p>
          <p className="text-xs text-muted-foreground">
            {[s.durationSec != null && сек(s.durationSec), s.bytes != null && объём(s.bytes),
              s.sourceFormat && `загружен как ${s.sourceFormat.toUpperCase()}`,
              s.uploadedAt && `${когда(s.uploadedAt)}, ${ктоСделал(s.uploadedBy)}`].filter(Boolean).join(' · ')}
          </p>
          <p className="text-xs">
            {s.usedBy?.length ? <>Звучит: {s.usedBy.map(гдеИспользуется).join(', ')}</> : <span className="text-muted-foreground">Нигде не звучит</span>}
          </p>
        </div>
        {!s.standard && !удалить && (
          <>
            <Button variant="outline" size="sm" onClick={() => void слушать()}>{звук ? <Square /> : <Play />}{звук ? 'Стоп' : 'Слушать'}</Button>
            <Button variant="outline" size="sm" onClick={onReplace}><Upload />Заменить</Button>
            <Button variant="outline" size="sm" onClick={() => setУдалить(true)} aria-label={`Удалить ${s.title || s.name}`}><Trash2 /></Button>
          </>
        )}
      </div>
      {удалить && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2">
          <span className="text-sm">
            {s.usedBy?.length ? 'Звук ещё звучит в правилах — узел не даст его удалить, пока его не уберут из мест выше.' : 'Удалить звук? Вернуть — только загрузив файл заново.'}
          </span>
          <Button size="sm" variant="destructive" disabled={идёт} onClick={() => void удалитьЗвук()}>Удалить</Button>
          <Button size="sm" variant="ghost" onClick={() => setУдалить(false)}>Нет</Button>
        </div>
      )}
      {звук && <audio controls autoPlay src={звук} className="w-full" onEnded={() => setЗвук(null)} />}
    </li>
  )
}

/** Загрузка своего файла или замена загруженного под тем же именем. */
function UploadForm({ замена, onDone, onCancel }: { замена: voice.Sound | null; onDone: () => Promise<unknown>; onCancel: () => void }) {
  const { companyId } = useCompany()
  const [файл, setФайл] = useState<File | null>(null)
  const [имя, setИмя] = useState('')
  const [название, setНазвание] = useState('')
  const [замечание, setЗамечание] = useState<string | null>(null)
  const [занято, setЗанято] = useState(false)
  const [идёт, setИдёт] = useState(false)
  const поле = useRef<HTMLInputElement>(null)

  const итогИмя = замена?.name ?? имя
  const имяГодно = ИМЯ.test(итогИмя)

  async function выбрать(f: File | null) {
    setФайл(f)
    setЗанято(false)
    setЗамечание(null)
    if (!f) return
    if (!замена) {
      setИмя(имяИзФайла(f.name))
      setНазвание(f.name.replace(/\.[^.]+$/, ''))
    }
    if (f.size > ПРЕДЕЛ_БАЙТ) { setЗамечание(`Файл ${объём(f.size)} — больше 10 МБ, узел его не примет.`); return }
    const d = await длительность(f)
    if (d != null && d > ПРЕДЕЛ_СЕК) setЗамечание(`Запись идёт ${сек(d)} — длиннее 5 минут, узел её не примет.`)
  }

  async function загрузить(заменить = !!замена) {
    if (!файл || !имяГодно) return
    setИдёт(true)
    try {
      const s = await voice.uploadSound(companyId, { name: итогИмя, title: замена ? замена.title : название.trim() || undefined, replace: заменить, file: файл })
      toast.success(заменить ? `Звук «${s.title || s.name}» заменён: места, где он звучит, звучат по-новому` : `Звук «${s.title || s.name}» загружен`)
      setФайл(null)
      setИмя('')
      setНазвание('')
      setЗанято(false)
      if (поле.current) поле.current.value = ''
      await onDone()
    } catch (e) {
      if (e instanceof voice.VoiceError && e.code === 'sound_exists') setЗанято(true)
      else toast.error(e instanceof Error ? e.message : 'Звук не загружен')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <section aria-label={замена ? 'Заменить звук' : 'Загрузить звук'}
      className={cn('space-y-3 rounded-xl border bg-card p-4', замена ? 'border-primary/35' : 'border-border')}>
      <h2 className="font-headline text-base font-semibold">{замена ? `Заменить «${замена.title || замена.name}»` : 'Загрузить свою запись'}</h2>
      <p className="text-xs text-muted-foreground">
        WAV, MP3 или OGG до 10 МБ и 5 минут. Узел приведёт запись к 8 кГц моно — так её играет Asterisk;
        послушайте результат после загрузки.{замена && ' Места, где звук используется, сразу зазвучат по-новому.'}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1 text-xs text-muted-foreground">
          <span className="block">Файл</span>
          <input ref={поле} type="file" accept=".wav,.mp3,.ogg,audio/wav,audio/mpeg,audio/ogg"
            onChange={e => void выбрать(e.target.files?.[0] ?? null)}
            className="block max-w-full text-sm text-foreground file:mr-2 file:rounded-md file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-sm" />
        </label>
        {!замена && (
          <>
            <label className="min-w-0 basis-48 flex-1 space-y-1 text-xs text-muted-foreground">
              <span className="block">Название</span>
              <Input value={название} onChange={e => setНазвание(e.target.value)} maxLength={200} placeholder="Приветствие линии" />
            </label>
            <label className="min-w-0 basis-48 flex-1 space-y-1 text-xs text-muted-foreground">
              <span className="block">Имя в правилах</span>
              <Input value={имя} onChange={e => { setИмя(e.target.value.toLowerCase()); setЗанято(false) }} maxLength={64}
                className="font-mono" placeholder="greeting-main" aria-invalid={!!имя && !имяГодно} />
            </label>
          </>
        )}
      </div>
      {!замена && !!имя && !имяГодно && (
        <p className="text-xs text-destructive">Имя — латиница, цифры, «-» и «_», начинается с буквы или цифры.</p>
      )}
      {!замена && !имя && файл && (
        <p className="text-xs text-muted-foreground">Задайте имя латиницей: по нему звук найдут правила (sound:custom/имя).</p>
      )}
      {замечание && <p className="text-xs text-warning">{замечание}</p>}
      {занято && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/50 bg-warning/5 p-2 text-sm">
          Звук «{итогИмя}» уже есть.
          <Button size="sm" disabled={идёт} onClick={() => void загрузить(true)}>Заменить его</Button>
          <span className="text-xs text-muted-foreground">или задайте другое имя</span>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!файл || !имяГодно || идёт || !!замечание} onClick={() => void загрузить()}>
          <Upload />{идёт ? 'Загружаем…' : замена ? 'Заменить' : 'Загрузить'}
        </Button>
        {замена && <Button variant="ghost" size="sm" onClick={onCancel}>Отмена</Button>}
      </div>
    </section>
  )
}
