/**
 * Карточка звонка: сводка, этапы по времени, запись и расшифровка, кто открывал.
 *
 * Номер — маской; целиком, запись и расшифровка открываются только по причине,
 * и каждое такое открытие узел пишет в журнал доступа. Внизу карточки видно, кто
 * и зачем уже открывал этот звонок: администратор, открывший номер, должен знать,
 * что его действие останется видно другим.
 *
 * Удалённая по сроку запись не пропадает, а показывается словами «удалена по
 * сроку»: иначе отсутствие записи выглядит как сбой.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Eye, FileText, Play, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as voice from '@/services/voiceService'
import {
  ИСХОД, ОБСЛУЖИЛ, ЭТАП, дата, когда, оператор, плохойИсход, сек, время,
} from './format'
import { ReasonDialog, Flags, NodeError } from './parts'

type Причина = { что: 'number' } | { что: 'transcript' } | { что: 'recording'; id: string }

const ДЕЙСТВИЕ: Record<string, string> = {
  'call.view': 'открыл карточку',
  'call.number': 'открыл номер',
  'call.search_number': 'искал по номеру',
  'transcript.read': 'открыл расшифровку',
  'recording.ticket': 'открыл запись',
  'recording.play': 'прослушал запись',
  'recording.download': 'скачал запись',
  'recording.delete': 'удалил запись досрочно',
  'retention.hold': 'запретил удаление',
  'retention.release': 'снял запрет удаления',
  'callback.cancel': 'снял обратный звонок',
}

const СТОРОНА: Record<string, string> = { caller: 'звонящий', operator: 'оператор', consult: 'консультация' }

export function CallCard({ contactId, onBack }: { contactId: string; onBack?: () => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [причина, setПричина] = useState<Причина | null>(null)
  const [номер, setНомер] = useState<string | null>(null)
  const [фразы, setФразы] = useState<voice.Segment[] | null>(null)
  const [звук, setЗвук] = useState<{ id: string; url: string } | null>(null)

  const карточка = useQuery({
    queryKey: ['voice-call', companyId, contactId],
    queryFn: () => voice.call(companyId, contactId),
  })
  const кто = useQuery({
    queryKey: ['voice-call-audit', companyId, contactId],
    queryFn: () => voice.audit(companyId, { contactId, limit: 50 }),
  })

  const к = карточка.data

  async function открыть(п: Причина, текст: string) {
    try {
      if (п.что === 'number') {
        setНомер((await voice.callNumber(companyId, contactId, текст)).number)
      } else if (п.что === 'transcript') {
        const t = await voice.transcript(companyId, contactId, текст)
        setФразы(t.segments)
        if (!t.segments.length) toast.info(t.purgedAt ? 'Расшифровка удалена по сроку хранения' : 'Расшифровки у этого звонка нет')
      } else {
        setЗвук({ id: п.id, url: await voice.recordingTicket(companyId, contactId, п.id, текст) })
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Узел не ответил')
      throw e
    } finally {
      // Строка журнала доступа появилась у узла — показываем её внизу карточки сразу.
      qc.invalidateQueries({ queryKey: ['voice-call-audit', companyId, contactId] })
    }
  }

  return (
    <div className="space-y-4 p-4">
      {onBack && (
        <Button variant="outline" size="sm" onClick={onBack}><ArrowLeft />К журналу</Button>
      )}
      {карточка.isLoading && <p role="status" className="text-sm">Открываем звонок…</p>}
      {карточка.isError && <NodeError ошибка={карточка.error} что="открыть звонок" />}

      {к && (
        <>
          <div className="space-y-1">
            <p className="font-mono text-xs text-muted-foreground">№ звонка {к.contactId}</p>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-headline text-lg font-semibold">
                {номер ?? (к.numberPurged ? 'номер удалён по сроку' : к.number || '—')}
              </span>
              <Flags флаги={к.flags} />
            </div>
            {!номер && !к.numberPurged && к.number && (
              <Button variant="outline" size="sm" onClick={() => setПричина({ что: 'number' })}>
                <Eye />Показать номер
              </Button>
            )}
            {к.identity && <p className="text-sm">{к.identity}</p>}
          </div>

          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Пришёл</dt><dd>{когда(к.startedAt)}</dd>
            <dt className="text-muted-foreground">Линия</dt><dd>{к.lineId}</dd>
            <dt className="text-muted-foreground">Исход</dt>
            <dd className={плохойИсход(к.outcome) ? 'text-destructive' : undefined}>
              {к.outcome ? ИСХОД[к.outcome] ?? к.outcome : 'идёт сейчас'}
            </dd>
            {к.servedBy && <><dt className="text-muted-foreground">Обслужил</dt><dd>{ОБСЛУЖИЛ[к.servedBy] ?? к.servedBy}</dd></>}
            <dt className="text-muted-foreground">Оператор</dt><dd>{оператор(к.operator)}</dd>
            <dt className="text-muted-foreground">Ожидание</dt><dd>{сек(к.waitSec)}</dd>
            <dt className="text-muted-foreground">Разговор</dt><dd>{сек(к.talkSec)}</dd>
            {!!к.holdSec && <><dt className="text-muted-foreground">Удержание</dt><dd>{сек(к.holdSec)}</dd></>}
            {к.topic && <><dt className="text-muted-foreground">Тема</dt><dd className="font-mono text-xs">{к.topic}</dd></>}
            {к.disposition?.note && <><dt className="text-muted-foreground">Итог</dt><dd>{к.disposition.note}</dd></>}
            {к.disposition?.ticketRef && <><dt className="text-muted-foreground">Заявка</dt><dd className="font-mono text-xs">{к.disposition.ticketRef}</dd></>}
            {к.retentionHold && <><dt className="text-muted-foreground">Не удалять</dt><dd>до {дата(к.retentionHold)}</dd></>}
          </dl>

          {!!к.stages?.length && (
            <section className="space-y-1">
              <h2 className="text-sm font-medium">Ход звонка</h2>
              <ol className="space-y-0.5 border-l border-border pl-3">
                {к.stages.map((э, i) => (
                  <li key={`${э.stage}-${i}`} className="flex gap-3 text-sm">
                    <span className="w-16 shrink-0 font-mono text-xs leading-5 text-muted-foreground">{время(э.at)}</span>
                    <span>{ЭТАП[э.stage] ?? <span className="font-mono text-xs">{э.stage}</span>}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="space-y-2">
            <h2 className="text-sm font-medium">Запись и расшифровка</h2>
            {!к.recordings?.length && <p className="text-sm text-muted-foreground">Записи у звонка нет.</p>}
            {к.recordings?.map(з => (
              <div key={з.id} className="space-y-1.5 rounded-lg border border-border p-2.5 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 flex-1">
                    {СТОРОНА[з.side] ?? з.side}{з.leg ? ` · нога ${з.leg}` : ''}
                    {з.durationSec != null && <span className="text-muted-foreground"> · {сек(з.durationSec)}</span>}
                  </span>
                  {з.purged
                    ? <span className="text-xs text-muted-foreground">удалена по сроку</span>
                    : (
                      <Button variant="outline" size="xs" onClick={() => setПричина({ что: 'recording', id: з.id })}>
                        <Play />Открыть запись
                      </Button>
                    )}
                </div>
                {!з.purged && з.purgeAt && <p className="text-xs text-muted-foreground">Хранится до {дата(з.purgeAt)}</p>}
                {звук?.id === з.id && (
                  // Ссылка разовая: одно открытие за 60 с, повторное прослушивание — новый запрос с причиной.
                  <audio controls autoPlay src={звук.url} className="w-full" onEnded={() => setЗвук(null)} />
                )}
              </div>
            ))}
            {к.transcribed && !фразы && (
              <Button variant="outline" size="sm" onClick={() => setПричина({ что: 'transcript' })}>
                <FileText />Открыть расшифровку
              </Button>
            )}
            {фразы && фразы.length > 0 && (
              <ol className="max-h-80 space-y-1 overflow-y-auto rounded-lg border border-border p-2.5 text-sm">
                {фразы.map(ф => (
                  <li key={ф.segmentId} className="flex gap-2">
                    <span className="w-20 shrink-0 text-xs leading-5 text-muted-foreground">
                      {ф.side === 'caller' ? 'звонящий' : 'оператор'} {сек(ф.startMs / 1000)}
                    </span>
                    <span>{ф.text}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="space-y-1 border-t border-border pt-3">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" />Открывали этот звонок
            </h2>
            {кто.isError && <p className="text-xs text-muted-foreground">Журнал доступа сейчас не читается.</p>}
            {кто.data && кто.data.items.length === 0 && <p className="text-xs text-muted-foreground">Пока никто.</p>}
            {кто.data?.items.map(з => (
              <p key={з.id} className="text-xs">
                <span className="text-muted-foreground">{когда(з.at)}</span>
                {' · '}{з.actor.name ?? з.actor.sub ?? 'служебный вход'} {ДЕЙСТВИЕ[з.action] ?? з.action}
                {з.reason && <span className="text-muted-foreground"> · «{з.reason}»</span>}
              </p>
            ))}
          </section>
        </>
      )}

      <ReasonDialog открыт={!!причина} onClose={() => setПричина(null)}
        заголовок={причина?.что === 'number' ? 'Показать номер целиком'
          : причина?.что === 'transcript' ? 'Открыть расшифровку' : 'Открыть запись'}
        действие={причина?.что === 'number' ? 'Показать номер' : 'Открыть'}
        onSubmit={т => (причина ? открыть(причина, т) : undefined)} />
    </div>
  )
}
