/**
 * Черновик настроек узла: правка → автосохранение → проверка → применение с комментарием.
 *
 * Один механизм на правила приёма, паспорт и политику хранения (docs/voice-app.html,
 * §6): действующие настройки не меняются до «Применить», черновик у вида один на
 * узел, его автор виден. Правка снимает отметку проверки — «Применить» доступно
 * только после проверки последней правки, так же решает и сам узел (409 not_validated).
 *
 * Сохраняем сами, без кнопки «Сохранить»: через ~0,8 с после последней правки, по
 * одной записи за раз с ETag черновика. Если тем временем черновик правил другой
 * администратор (412), показываем его версию и говорим об этом словами.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import * as voice from '@/services/voiceService'
import { показать, поУказателю, разница, type Изменение } from './draftDoc'

// ——— Черновик вида ———

export async function черновикВида(cid: string, kind: voice.ConfigKind) {
  const [d, v] = await Promise.all([
    voice.configVersions(cid, kind, { state: 'draft', limit: 1 }),
    voice.configVersions(cid, kind, { state: 'validated', limit: 1 }),
  ])
  return d.items[0] ?? v.items[0] ?? null
}

type Сохранение = 'idle' | 'saving' | 'saved' | 'error'

export interface Черновик<B> {
  загрузка: boolean
  ошибка: unknown
  действующая?: voice.ConfigVersion<B>
  черновик: voice.ConfigVersion<B> | null
  /** что на экране: несохранённая правка → черновик → действующая */
  тело?: B
  /** изменения от действующей версии */
  изменено: Изменение[]
  /** прежнее значение поля, если оно изменено в черновике; иначе undefined */
  было: (path: string) => string | undefined
  изменить: (f: (b: B) => B) => void
  сохранение: Сохранение
  сохраненоВ: Date | null
  проверка: voice.Validation | null
  проверяем: boolean
  проверить: () => Promise<void>
  применяем: boolean
  применить: (comment: string) => Promise<boolean>
  отменить: () => Promise<void>
}

export function useDraft<B extends object>(kind: voice.ConfigKind): Черновик<B> {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const ключ = useMemo(() => ['voice-config', companyId, kind] as const, [companyId, kind])

  const действующая = useQuery({
    queryKey: [...ключ, 'active'],
    queryFn: async () => (await voice.configActive(companyId, kind)).data as voice.ConfigVersion<B>,
  })
  const черновик = useQuery({
    queryKey: [...ключ, 'draft'],
    queryFn: async () => (await черновикВида(companyId, kind)) as voice.ConfigVersion<B> | null,
  })

  const [правка, setПравка] = useState<B | null>(null)
  const [сохранение, setСохранение] = useState<Сохранение>('idle')
  const [сохраненоВ, setСохраненоВ] = useState<Date | null>(null)
  const [проверка, setПроверка] = useState<voice.Validation | null>(null)
  const [проверяем, setПроверяем] = useState(false)
  const [применяем, setПрименяем] = useState(false)

  const ждёт = useRef<B | null>(null)
  const таймер = useRef<ReturnType<typeof setTimeout> | null>(null)
  const очередь = useRef<Promise<void>>(Promise.resolve())

  const положить = useCallback((v: voice.ConfigVersion<B> | null) => {
    qc.setQueryData([...ключ, 'draft'], v)
  }, [qc, ключ])

  const записатьНаУзел = useCallback(async () => {
    const тело = ждёт.current
    if (!тело) return
    ждёт.current = null
    setСохранение('saving')
    try {
      const d = qc.getQueryData<voice.ConfigVersion<B> | null>([...ключ, 'draft']) ?? null
      let saved: voice.ConfigVersion<B>
      if (!d) {
        try {
          saved = await voice.configDraft(companyId, kind, { body: тело }) as voice.ConfigVersion<B>
        } catch (e) {
          // Черновик успел завести другой администратор: пишем поверх его черновика по его ETag.
          if (!(e instanceof voice.VoiceError && e.code === 'draft_exists')) throw e
          const чужой = await черновикВида(companyId, kind) as voice.ConfigVersion<B> | null
          if (!чужой?.etag) throw e
          saved = (await voice.configSaveDraft(companyId, kind, чужой.version, чужой.etag, тело)).data as voice.ConfigVersion<B>
        }
      } else {
        saved = (await voice.configSaveDraft(companyId, kind, d.version, d.etag ?? `"${d.version}.0"`, тело)).data as voice.ConfigVersion<B>
      }
      положить(saved)
      setСохранение('saved')
      setСохраненоВ(new Date())
      if (!ждёт.current) setПравка(null)
    } catch (e) {
      setСохранение('error')
      if (e instanceof voice.VoiceError && (e.status === 412 || e.code === 'not_draft')) {
        toast.error('Черновик тем временем изменил или применил другой администратор. Показываем то, что сейчас у узла: повторите свою правку.')
        ждёт.current = null
        setПравка(null)
        await qc.invalidateQueries({ queryKey: ключ })
      } else {
        // Правку не теряем: она остаётся на экране и уйдёт со следующей.
        ждёт.current = ждёт.current ?? тело
        toast.error(e instanceof Error ? `Черновик не сохранён: ${e.message}` : 'Черновик не сохранён')
      }
    }
  }, [qc, ключ, companyId, kind, положить])

  /** Записи по одной: следующая ждёт ETag предыдущей. */
  const сброс = useCallback(() => {
    if (таймер.current) { clearTimeout(таймер.current); таймер.current = null }
    очередь.current = очередь.current.then(записатьНаУзел)
    return очередь.current
  }, [записатьНаУзел])

  // Ушли с экрана раньше автосохранения — правку дописываем, а не теряем.
  useEffect(() => () => {
    if (таймер.current) { clearTimeout(таймер.current); таймер.current = null; void сброс() }
  }, [сброс])

  const основа = правка ?? черновик.data?.body ?? действующая.data?.body
  const изменено = useMemo(() => (действующая.data && основа ? разница(действующая.data.body, основа) : []), [действующая.data, основа])

  const изменить = useCallback((f: (b: B) => B) => {
    const текущее = ждёт.current ?? правка ?? черновик.data?.body ?? действующая.data?.body
    if (!текущее) return
    const next = f(текущее)
    ждёт.current = next
    setПравка(next)
    setПроверка(null)
    setСохранение('idle')
    if (таймер.current) clearTimeout(таймер.current)
    таймер.current = setTimeout(() => { void сброс() }, 800)
  }, [правка, черновик.data, действующая.data, сброс])

  const было = useCallback((path: string) => {
    const ch = изменено.find(x => x.path === path || x.path.startsWith(`${path}/`))
    return ch ? показать(поУказателю(действующая.data?.body, path)) : undefined
  }, [изменено, действующая.data])

  async function проверить() {
    setПроверяем(true)
    try {
      await сброс()
      const d = qc.getQueryData<voice.ConfigVersion<B> | null>([...ключ, 'draft'])
      if (!d) { toast.info('Изменений нет — проверять нечего'); return }
      setПроверка(await voice.configValidate(companyId, kind, d.version))
      await qc.invalidateQueries({ queryKey: [...ключ, 'draft'] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Проверка не удалась')
    } finally {
      setПроверяем(false)
    }
  }

  async function применить(comment: string) {
    setПрименяем(true)
    try {
      await сброс()
      const d = qc.getQueryData<voice.ConfigVersion<B> | null>([...ключ, 'draft'])
      const a = действующая.data
      if (!d || !a) return false
      const v = (await voice.configApply(companyId, kind, d.version, a.etag ?? `"${a.version}"`, comment)).data
      toast.success(`Действует r${v.version}`)
      setПроверка(null)
      // Цели перевода и журнал изменений собраны из тех же версий — освежаем всё, что от них зависит.
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['voice-config', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-targets', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-versions', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-changes', companyId] }),
      ])
      return true
    } catch (e) {
      if (e instanceof voice.VoiceError && e.code === 'config_invalid') {
        setПроверка({ ok: false, issues: e.issues ?? [] })
      } else {
        toast.error(e instanceof Error ? e.message : 'Не применено')
        if (e instanceof voice.VoiceError && (e.status === 412 || e.code === 'not_validated')) {
          setПроверка(null)
          await qc.invalidateQueries({ queryKey: ключ })
        }
      }
      return false
    } finally {
      setПрименяем(false)
    }
  }

  async function отменить() {
    if (таймер.current) { clearTimeout(таймер.current); таймер.current = null }
    ждёт.current = null
    await очередь.current
    const d = qc.getQueryData<voice.ConfigVersion<B> | null>([...ключ, 'draft'])
    try {
      if (d) await voice.configDeleteDraft(companyId, kind, d.version)
      setПравка(null)
      setПроверка(null)
      setСохранение('idle')
      положить(null)
      await qc.invalidateQueries({ queryKey: ['voice-versions', companyId] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Черновик не удалён')
    }
  }

  return {
    загрузка: действующая.isLoading || черновик.isLoading,
    ошибка: действующая.error ?? черновик.error,
    действующая: действующая.data,
    черновик: черновик.data ?? null,
    тело: основа,
    изменено, было, изменить,
    сохранение, сохраненоВ,
    проверка, проверяем, проверить,
    применяем, применить, отменить,
  }
}
