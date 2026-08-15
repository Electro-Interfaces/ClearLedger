/**
 * Витрина по ссылке — страница для того, у кого нет учётки.
 *
 * Открывается без входа: заказчик не станет заводить пароль ради одного экрана.
 * Отсюда ничего нельзя сделать — ни написать, ни ответить: аноним с ссылкой
 * смотрит, но не действует.
 *
 * Тело витрины — тот же компонент, что и внутри пространства (`ShowcaseBody`).
 * Своя копия уже разошлась с оригиналом: потеряла тон предупреждения у проблемной
 * цифры, и одна и та же витрина по ссылке выглядела спокойнее, чем на самом деле.
 */
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { Card, CardContent } from '@/components/ui/card'
import { getShowcaseByToken } from '@/pulse/pulseService'
import { ShowcaseCanvas } from '@/pulse/ShowcaseView'

export function ShowcaseLinkPage() {
  const { token = '' } = useParams()
  const q = useQuery({
    queryKey: ['showcase-link', token],
    queryFn: () => getShowcaseByToken(token),
    retry: false,
  })

  if (q.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <Card className="max-w-sm">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Ссылка недействительна: её отозвали или истёк срок.
            Попросите новую у того, кто её присылал.
          </CardContent>
        </Card>
      </div>
    )
  }
  if (!q.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Загрузка…
      </div>
    )
  }
  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6">
      <ShowcaseCanvas data={q.data} />
    </div>
  )
}
