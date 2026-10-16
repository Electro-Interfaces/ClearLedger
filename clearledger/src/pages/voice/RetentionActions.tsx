/**
 * Хранение одного звонка в его карточке: запрет удаления по сроку (спор, проверка) и
 * досрочное удаление записей и расшифровки (требование звонящего, решение заказчика).
 *
 * Оба действия — с причиной и в журнал доступа. Досрочное удаление необратимо, поэтому
 * сначала словами говорим, что пропадёт и что останется (строка журнала звонка).
 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Lock, Trash2, Unlock } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import * as voice from '@/services/voiceService'
import { дата } from './format'

/** Дата «ГГГГ-ММ-ДД» через `дней` от сегодня — по UTC, как её понимает узел. */
function деньUTC(дней: number) {
  return new Date(Date.now() + дней * 86_400_000).toISOString().slice(0, 10)
}

export function RetentionActions({ к }: { к: voice.CallCard }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [что, setЧто] = useState<'hold' | 'release' | 'delete' | null>(null)
  const [до, setДо] = useState(() => деньUTC(90))
  const [причина, setПричина] = useState('')
  const [идёт, setИдёт] = useState(false)
  const есть = !!к.recordings?.some(з => !з.purged) || !!к.transcribed
  const идётЗвонок = !к.outcome

  async function сделать() {
    setИдёт(true)
    try {
      if (что === 'hold') {
        await voice.holdCall(companyId, к.contactId, до, причина.trim())
        toast.success(`Записи звонка не удалятся по сроку до ${дата(до)}`)
      } else if (что === 'release') {
        await voice.releaseHold(companyId, к.contactId)
        toast.success('Запрет снят: записи удалятся по обычному сроку')
      } else if (что === 'delete') {
        await voice.deleteRecordings(companyId, к.contactId, причина.trim())
        toast.success('Записи и расшифровка звонка удалены')
      }
      setЧто(null)
      setПричина('')
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['voice-call', companyId, к.contactId] }),
        qc.invalidateQueries({ queryKey: ['voice-call-audit', companyId, к.contactId] }),
      ])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Узел не выполнил действие')
    } finally {
      setИдёт(false)
    }
  }

  if (идётЗвонок) return null
  const годна = что === 'release' || причина.trim().length >= 3
  const сегодня = деньUTC(0)

  return (
    <div className="space-y-2">
      {!что && (
        <div className="flex flex-wrap gap-2">
          {к.retentionHold
            ? <Button variant="outline" size="sm" onClick={() => setЧто('release')}><Unlock />Снять запрет удаления</Button>
            : <Button variant="outline" size="sm" onClick={() => setЧто('hold')}><Lock />Не удалять по сроку…</Button>}
          {есть && !к.retentionHold && (
            <Button variant="outline" size="sm" onClick={() => setЧто('delete')}><Trash2 />Удалить записи досрочно…</Button>
          )}
        </div>
      )}
      {что && (
        <form className="space-y-2 rounded-lg border border-border p-3 text-sm" onSubmit={e => { e.preventDefault(); if (годна) void сделать() }}>
          {что === 'hold' && (
            <>
              <p>Записи, расшифровка и номер звонка не удалятся по сроку до выбранной даты включительно. Новый запрет заменяет прежний.</p>
              <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                до
                <Input type="date" value={до} min={сегодня} onChange={e => setДо(e.target.value)} className="h-9 w-44" aria-label="Не удалять до" />
              </label>
            </>
          )}
          {что === 'release' && <p>Снять запрет? Записи удалятся при ближайшей чистке, если их срок уже прошёл.</p>}
          {что === 'delete' && (
            <p className="text-destructive">
              Удалить записи и расшифровку звонка сейчас? Их не вернуть. Строка в журнале звонков останется, выданные ссылки на звук перестанут работать.
            </p>
          )}
          {что !== 'release' && (
            <Textarea value={причина} onChange={e => setПричина(e.target.value)} maxLength={500} rows={2} aria-label="Причина"
              placeholder={что === 'hold' ? 'Например: спор со звонящим, проверка по жалобе' : 'Например: требование звонящего об удалении записи'} />
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" size="sm" variant={что === 'delete' ? 'destructive' : 'default'} disabled={!годна || идёт || (что === 'hold' && до < сегодня)}>
              {идёт ? 'Выполняем…' : что === 'hold' ? 'Запретить удаление' : что === 'release' ? 'Снять запрет' : 'Удалить'}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setЧто(null)}>Отмена</Button>
          </div>
          {что !== 'release' && <p className="text-xs text-muted-foreground">Причина попадёт в журнал доступа узла вместе с вашим именем.</p>}
        </form>
      )}
    </div>
  )
}
