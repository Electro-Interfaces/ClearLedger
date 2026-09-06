/**
 * Избранные приложения человека — один список на пространство.
 *
 * Тот же список, что «Закреплённые приложения» в настройке пульта: отметил
 * звёздочкой в каталоге — увидел на пульте. Хранится на сервере, потому что
 * телефон и рабочий компьютер обязаны показывать одно и то же.
 *
 * Потребителей двое: каталог пространства и быстрое меню в рельсе.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { getFavoriteApps, saveFavoriteApps } from '@/services/ssoService'

/** Столько приложений принимает избранное — предел настроек пульта (`favorite_apps`). */
export const FAVORITE_LIMIT = 12

export function useFavoriteApps() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const key = ['launcher-favorites', company.id]
  const query = useQuery({
    queryKey: key,
    queryFn: () => getFavoriteApps(company.id),
    enabled: isApiEnabled() && !!company.id,
    staleTime: 5 * 60_000,
  })
  const favorites = query.data ?? []
  const mutation = useMutation({
    mutationFn: (codes: string[]) => saveFavoriteApps(company.id, codes),
    onSuccess: (codes) => {
      qc.setQueryData(key, codes)
      // Пульт показывает тот же список — пусть перечитает, а не ждёт своего срока.
      qc.invalidateQueries({ queryKey: ['pulse-home-settings', company.id] })
    },
    onError: (e) => toast.error('Не удалось сохранить избранное',
      { description: (e as Error).message }),
  })

  function toggle(code: string) {
    const next = favorites.includes(code)
      ? favorites.filter((x) => x !== code)
      : [...favorites, code]
    if (next.length > FAVORITE_LIMIT) {
      toast.error(`В избранном не больше ${FAVORITE_LIMIT} приложений`,
        { description: 'Снимите звёздочку с ненужного и отметьте это.' })
      return
    }
    // Звёздочка отвечает сразу, ответ сервера лишь подтверждает: ждать сети,
    // чтобы увидеть нажатие, на телефоне читается как «не сработало».
    qc.setQueryData(key, next)
    mutation.mutate(next, {
      // Сеть подвела — возвращаем звёздочку туда, где она была до нажатия.
      onError: () => qc.setQueryData(key, favorites),
    })
  }

  return { favorites, ready: query.isSuccess, toggle }
}
