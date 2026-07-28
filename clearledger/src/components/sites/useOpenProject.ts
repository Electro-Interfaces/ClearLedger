/**
 * Переход к рабочему экрану проекта.
 *
 * Проект открывается не модалкой, а полноэкранным пунктом «Проект»: id кладётся
 * в URL, туда же переключается под-раздел. Это одна ссылка, поэтому её можно
 * дёргать из любого реестра — проектов, присоединений, оборудования, карты.
 */
import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

export function useOpenProject(): (id: string) => void {
  const [, setParams] = useSearchParams()
  return useCallback((id: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('project', id)
      // Проект ведут в разделе «Работа» — открываем именно там, откуда бы ни пришли
      // (из аналитики, карты, реестра присоединений).
      next.set('mode', 'projects')
      next.set('sub', 'pr_project')
      return next
    }, { replace: true })
  }, [setParams])
}
