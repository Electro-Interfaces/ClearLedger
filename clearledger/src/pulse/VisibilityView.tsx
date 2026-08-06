/**
 * «Пульс» → «Экран дня» → «Кто что видит»: отбор картины для роли.
 *
 * Пороги отвечают «когда реагировать», этот экран — «кому это показывать».
 * Куратор — руководитель верхнего уровня: ему нужна картина, а не весь разбор,
 * и решает, что входит в эту картину, директор, а не разработчик.
 *
 * Отбор пишется в ту же роль, которой человек назначен в «Управлении», — второй
 * системы прав здесь нет. Поэтому снятая галочка означает не «спрятали с глаз»,
 * а «закрыли доступ»: API отдаёт такому человеку раздел пустым, и сообщения этой
 * темы не попадают к нему на экран дня.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Eye, ShieldCheck, Users } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseVisibility, savePulseVisibility } from './pulseService'
import { PulseError, PulseLoading } from './parts'

export function VisibilityView() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const q = useQuery({
    queryKey: ['pulse-visibility', company.id],
    queryFn: () => getPulseVisibility(company.id),
  })
  const [roleId, setRoleId] = useState<string | null>(null)
  const [picked, setPicked] = useState<Set<string> | null>(null)

  // Роль по умолчанию — та, ради которой экран и сделан: куратор.
  useEffect(() => {
    const roles = q.data?.roles ?? []
    if (!roles.length || roleId) return
    const curator = roles.find((r) => /куратор/i.test(r.name)) ?? roles.find((r) => !r.full)
    if (curator) { setRoleId(curator.id); setPicked(new Set(curator.items)) }
  }, [q.data, roleId])

  const save = useMutation({
    mutationFn: () => savePulseVisibility(company.id, roleId!, [...(picked ?? [])]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pulse-visibility', company.id] })
      toast.success('Отбор сохранён — роль увидит только отмеченное')
    },
    onError: () => toast.error('Не удалось сохранить отбор'),
  })

  if (q.isLoading) return <PulseLoading what="состава картины" />
  if (q.isError) return <PulseError what="состав картины" onRetry={() => q.refetch()} />
  const d = q.data
  if (!d) return null

  const role = d.roles.find((r) => r.id === roleId) ?? null
  const sections = [...new Set(d.items.map((i) => i.section))]
  const toggle = (key: string) => setPicked((prev) => {
    const next = new Set(prev ?? [])
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Роль
        </h2>
        <div className="flex flex-wrap gap-2">
          {d.roles.map((r) => (
            <button key={r.id} type="button"
              onClick={() => { setRoleId(r.id); setPicked(new Set(r.items)) }}
              className={cn('flex min-h-9 items-center gap-2 rounded-md border px-3 text-[13px] transition-colors',
                r.id === roleId ? 'border-primary/50 bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:bg-accent/40')}>
              {r.full ? <ShieldCheck className="h-3.5 w-3.5" /> : <Users className="h-3.5 w-3.5" />}
              {r.name}
              {!!r.people && <span className="text-[11px] text-muted-foreground">· {r.people}</span>}
            </button>
          ))}
        </div>
      </section>

      {role?.full ? (
        <Card className="border-dashed py-0">
          <CardContent className="p-4 text-xs text-muted-foreground">
            У роли «{role.name}» полный доступ — отбирать нечего. Чтобы ограничить
            картину, назначьте человеку роль с явным набором прав.
          </CardContent>
        </Card>
      ) : role ? (
        <>
          <div className="flex items-start justify-between gap-3">
            <p className="max-w-2xl text-xs text-muted-foreground">
              Отмеченное входит в картину роли «{role.name}»: эти разделы открываются,
              и только сообщения этих тем попадают к ней на экран дня. Снятая галочка
              закрывает доступ, а не прячет пункт.
            </p>
            <div className="flex shrink-0 gap-2">
              {/* Проверка отбора глазами роли: права не меняются, «Пульс» просто
                  показывает ту же картину так, как её увидит этот человек. */}
              <Button size="sm" variant="outline" className="h-9 sm:h-8"
                onClick={() => navigate(`/pulse?as=${role.id}`)}>
                <Eye className="mr-1 h-3.5 w-3.5" />Посмотреть глазами
              </Button>
              <Button size="sm" className="h-9 sm:h-8"
                disabled={save.isPending} onClick={() => save.mutate()}>
                Сохранить
              </Button>
            </div>
          </div>

          {sections.map((section) => (
            <section key={section} className="space-y-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                {section}
              </h2>
              <Card className="py-0">
                <CardContent className="divide-y divide-border/40 p-0">
                  {d.items.filter((i) => i.section === section).map((i) => {
                    const on = picked?.has(i.key) ?? false
                    return (
                      <button key={i.key} type="button" onClick={() => toggle(i.key)}
                        aria-pressed={on}
                        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-accent/40">
                        {/* Цель нажатия — строка целиком: в квадратик 20 px на
                            телефоне попасть нельзя, а список длинный. */}
                        <span className={cn('flex h-5 w-5 shrink-0 items-center justify-center rounded border',
                          on ? 'border-primary bg-primary text-primary-foreground' : 'border-border')}>
                          {on && <Check className="h-3.5 w-3.5" />}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[13px]">{i.label}</span>
                        {!on && (
                          <Badge variant="outline"
                            className="shrink-0 px-1.5 py-0 text-[10px] font-normal text-muted-foreground">
                            закрыто
                          </Badge>
                        )}
                      </button>
                    )
                  })}
                </CardContent>
              </Card>
            </section>
          ))}
        </>
      ) : (
        <Card className="border-dashed py-0">
          <CardContent className="p-4 text-xs text-muted-foreground">
            Ролей с явным набором прав пока нет. Заведите роль «Куратор» в
            «Управлении» — и здесь можно будет отобрать, что она видит.
          </CardContent>
        </Card>
      )}
    </div>
  )
}
