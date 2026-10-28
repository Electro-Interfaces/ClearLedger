/** Мои теги и на чём они висят — общий кэш для календаря, «Трека» и карточек. */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as tagsService from '@/services/tagsService'
import type { PersonalTag } from '@/services/tagsService'

export type PersonalTagsData = Awaited<ReturnType<typeof tagsService.listTags>>

export function usePersonalTags(companyId: string) {
  const q = useQuery({
    queryKey: ['personal-tags', companyId],
    queryFn: () => tagsService.listTags(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  const tags = useMemo(() => q.data?.tags ?? [], [q.data])
  const links = useMemo(() => q.data?.links ?? {}, [q.data])
  const byId = useMemo(() => new Map(tags.map((t) => [t.id, t])), [tags])
  const tagsOf = (ref: string): PersonalTag[] =>
    (links[ref] ?? []).map((id) => byId.get(id)).filter((t): t is PersonalTag => !!t)
      .sort((a, b) => a.position - b.position)
  return { tags, links, tagsOf, loading: q.isLoading }
}

