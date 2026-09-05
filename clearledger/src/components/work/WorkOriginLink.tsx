import { useQuery } from '@tanstack/react-query'
import { useSupportContext } from '@/contexts/SupportContext'
import { getWorkOrigin } from '@/services/workContextService'

export function WorkOriginLink({ companyId, kind, id }: { companyId: string; kind: 'doc' | 'task'; id: string }) {
  const { openInteraction } = useSupportContext()
  const q = useQuery({ queryKey: ['work-origin', companyId, kind, id], queryFn: () => getWorkOrigin(companyId, kind, id) })
  if (!q.data?.origin) return null
  const origin = q.data.origin
  return <button type="button" className="text-sm text-primary underline underline-offset-4"
    onClick={() => openInteraction('chat', `room:${origin.room_id}:message:${origin.message_id}`)}>Исходное сообщение</button>
}
