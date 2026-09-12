/**
 * «Спросить поддержку» — обращение к поставщику программы прямо из карточки.
 *
 * Замысел (docs/BRIDGE.md §4.2): человек находит непонятное в документе, задаче
 * или объекте — и спрашивает оттуда же, а не пересказывает в отдельном окне «у
 * меня в одном документе что-то не так». Предмет уезжает НАЗВАНИЕМ и номером,
 * а не данными: оператор понимает, о чём речь, а за данными при необходимости
 * входит пропуском в пространство клиента.
 *
 * Кнопки нет, когда связи нет: пространство может быть ещё не связано с
 * поддержкой, и «написать некому» человек должен узнать до того, как напишет, а
 * не после отправки.
 */
import { useQuery } from '@tanstack/react-query'
import { LifeBuoy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import {
  listPartnerSpaces, subjectTopics, TOPIC_STATE_NAME,
} from '@/services/partnerSpaceService'

/** Предмет обращения: вид, идентификатор у себя и как его назвать соседу. */
export interface AskSubject {
  kind: 'doc' | 'task' | 'object' | 'ticket' | 'shift' | 'product'
  ref: string
  /** «Договор ВХ-114 от 02.09», «Объект 208, АЗС Светогорск» — номер и название. */
  label: string
}

const PREFIX = 'ask:'
const TOPIC_PREFIX = 'topic:'

/** Контекст вызова панели поддержки. Строкой — таким контекст в панели и был. */
export const askContext = (s: AskSubject) =>
  `${PREFIX}${s.kind}:${s.ref}:${s.label}`

/** Открыть уже заведённое обращение: код пространства и код обращения. */
export const topicContext = (partnerCode: string, topicCode: string) =>
  `${TOPIC_PREFIX}${partnerCode}:${topicCode}`

export function parseTopicContext(context: string | null): { partner: string; topic: string } | null {
  if (!context || !context.startsWith(TOPIC_PREFIX)) return null
  const [partner, topic] = context.slice(TOPIC_PREFIX.length).split(':')
  return partner && topic ? { partner, topic } : null
}

export function parseAskContext(context: string | null): AskSubject | null {
  if (!context || !context.startsWith(PREFIX)) return null
  // Название содержит и двоеточия, и пробелы — поэтому режем ровно дважды.
  const rest = context.slice(PREFIX.length)
  const first = rest.indexOf(':')
  const second = rest.indexOf(':', first + 1)
  if (first < 0 || second < 0) return null
  return {
    kind: rest.slice(0, first) as AskSubject['kind'],
    ref: rest.slice(first + 1, second),
    label: rest.slice(second + 1),
  }
}

export function AskSupportButton({ subject, size = 'sm', variant = 'outline' }: {
  subject: AskSubject
  size?: 'sm' | 'default' | 'icon'
  variant?: 'outline' | 'ghost' | 'default'
}) {
  const { companyId } = useCompany()
  const { openInteraction } = useSupportContext()
  const spaces = useQuery({
    queryKey: ['partner-spaces', companyId],
    queryFn: () => listPartnerSpaces(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60_000,
  })
  const vendor = spaces.data?.items.find((p) => p.role === 'vendor' && p.isActive && p.linked)
  // Что уже спрашивали по этой карточке. Без этого один документ уезжает третьим
  // обращением, а первые два висят открытыми у оператора.
  const asked = useQuery({
    queryKey: ['subject-topics', subject.kind, subject.ref, companyId],
    queryFn: () => subjectTopics(subject.kind, subject.ref, companyId),
    enabled: !!companyId && !!vendor,
    staleTime: 60_000,
  })
  if (!vendor) return null
  const open = (asked.data?.items || []).filter((t) => t.state !== 'closed')

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {open.map((t) => (
        <Button key={t.code} variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs"
          title={t.title}
          onClick={() => openInteraction('tickets', topicContext(t.partnerCode, t.code))}>
          <LifeBuoy className="h-3.5 w-3.5 text-primary" />
          {t.number ? `${t.number} · ` : ''}{TOPIC_STATE_NAME[t.state]}
        </Button>
      ))}
      <Button variant={variant} size={size} className="gap-2"
        onClick={() => openInteraction('tickets', askContext(subject))}>
        <LifeBuoy className="h-4 w-4" />
        {size === 'icon' ? '' : open.length ? 'Ещё вопрос' : 'Спросить поддержку'}
      </Button>
    </span>
  )
}
