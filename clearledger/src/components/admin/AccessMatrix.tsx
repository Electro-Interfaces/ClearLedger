/**
 * Матрица доступа пространства: строки — продукты и их разделы, колонки — роли компании.
 *
 * Зачем таблица, а не список у каждой роли: доступ — это сравнение. «Кто ещё видит
 * Реестр сессий», «чем подрядчик отличается от сотрудника» в вертикальном списке по
 * одной роли не читается, приходится открывать четыре диалога подряд. Здесь весь
 * контур прав виден разом и правится в одном месте.
 *
 * Дерево прав = каталог подключённых компании продуктов (`/api/registry/access-catalog`,
 * он же решает, что компании вообще поставлено) + разделы продукта из
 * `config/productAccess.ts` (те же списки, которыми рисуется меню).
 *
 * Ключи те же, что и раньше: `<продукт>` — рабочее место целиком, `<продукт>:<раздел>` —
 * его часть. Отметка на продукте покрывает все его разделы (`app_allowed` на сервере).
 */
import { Fragment, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Check, ChevronDown, ChevronRight, Loader2, ShieldCheck, Table2 } from 'lucide-react'
import * as roleService from '@/services/roleService'
import type { CompanyRole } from '@/services/roleService'
import { useAccessTree } from '@/hooks/useAccessTree'
import { toggleAccessKey } from '@/lib/accessKeys'

/** Набор ключей роли → правки. null = полный доступ (отмечено всё, менять нечего). */
type Draft = Record<string, string[] | null>

export function AccessMatrix({ companyId, roles, canManage }: {
  companyId: string; roles: CompanyRole[]; canManage: boolean
}) {
  const qc = useQueryClient()
  const { tree, isLoading } = useAccessTree(companyId)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [draft, setDraft] = useState<Draft>({})
  const [saving, setSaving] = useState(false)

  const keysOf = (r: CompanyRole): string[] | null =>
    r.id in draft ? draft[r.id] : r.modules
  const dirty = Object.keys(draft).filter((id) => {
    const role = roles.find((r) => r.id === id)
    if (!role) return false
    const a = draft[id]; const b = role.modules
    if (a === null || b === null) return a !== b
    return a.length !== b.length || a.some((k) => !b.includes(k))
  })

  /** Переключить ключ у роли. Продукт снимается вместе со своими разделами. */
  const toggle = (role: CompanyRole, key: string, app: string) => {
    if (!canManage || role.is_system) return
    setDraft((d) => {
      const cur = role.id in d ? d[role.id] : role.modules
      // Полный доступ правится только через карточку роли: снятие одной галочки
      // превратило бы «все модули» в длинный явный список — это не то, чего ждут.
      if (cur === null) return d
      return { ...d, [role.id]: toggleAccessKey(cur, key, app) }
    })
  }

  const save = async () => {
    setSaving(true)
    try {
      for (const id of dirty) {
        const role = roles.find((r) => r.id === id)!
        await roleService.updateRole(id, companyId, role.name, draft[id])
      }
      toast.success(`Сохранено ролей: ${dirty.length}`)
      setDraft({})
      qc.invalidateQueries({ queryKey: ['company-roles', companyId] })
      qc.invalidateQueries({ queryKey: ['team-members', companyId] })
    } catch (e) {
      toast.error('Не сохранено', { description: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const editable = roles.filter((r) => !r.is_system)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Table2 className="h-5 w-5" /> Матрица доступа</CardTitle>
        <CardDescription>
          Что видит роль: продукт целиком или отдельные его разделы. Системные роли — только чтение,
          их можно скопировать в свою карточкой роли.
        </CardDescription>
        {/* CardAction — обязательная обёртка: CardHeader это grid, и кнопка без неё
            растягивается на всю ширину карточки. */}
        {canManage && (
          <CardAction>
            <Button size="sm" onClick={save} disabled={!dirty.length || saving}>
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
              Сохранить{dirty.length ? ` (${dirty.length})` : ''}
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Загрузка каталога…
          </div>
        )}
        {!isLoading && !editable.length && (
          <div className="text-sm text-muted-foreground mb-3">
            Кастомных ролей ещё нет — создайте роль, чтобы раздавать доступ точечно.
            Системные показаны для сравнения.
          </div>
        )}
        {/* Горизонтальная прокрутка — колонок столько, сколько ролей у компании. */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-card text-left font-medium text-xs uppercase tracking-wide text-muted-foreground/75 py-2 pr-3 min-w-[240px]">
                  Продукт и разделы
                </th>
                {roles.map((r) => (
                  <th key={r.id} className="px-2 py-2 text-center align-bottom min-w-[92px]">
                    <div className="text-xs font-medium truncate max-w-[120px] mx-auto" title={r.name}>{r.name}</div>
                    <div className="text-[10px] text-muted-foreground font-normal">
                      {r.is_system ? 'системная' : `${r.members_count} чел.`}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tree.map((app) => {
                const expanded = !!open[app.app]
                return (
                  <Fragment key={app.app}>
                    <tr className="border-t">
                      <td className="sticky left-0 z-10 bg-card py-1.5 pr-3">
                        <button type="button" disabled={!app.count}
                          onClick={() => setOpen((o) => ({ ...o, [app.app]: !o[app.app] }))}
                          className="flex items-center gap-1.5 font-medium hover:text-primary transition-colors disabled:hover:text-foreground">
                          {app.count > 0 && (expanded
                            ? <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                            : <ChevronRight className="h-3.5 w-3.5 opacity-60" />)}
                          {app.count === 0 && <span className="w-3.5" />}
                          <span>{app.name}</span>
                          {app.count > 0 && <span className="text-[11px] text-muted-foreground font-normal">· {app.count}</span>}
                        </button>
                      </td>
                      {roles.map((r) => (
                        <Cell key={r.id} role={r} keys={keysOf(r)} value={app.app}
                          onToggle={() => toggle(r, app.app, app.app)} canManage={canManage} strong />
                      ))}
                    </tr>
                    {expanded && app.groups.map((g) => (
                      <Fragment key={`${app.app}-${g.name}`}>
                        <tr>
                          <td className="sticky left-0 z-10 bg-card pl-7 pr-3 pt-2 pb-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                            {g.name}
                          </td>
                          <td colSpan={roles.length} />
                        </tr>
                        {g.modules.map((m) => (
                          <tr key={m.key} className="hover:bg-accent/30">
                            <td className="sticky left-0 z-10 bg-card pl-9 pr-3 py-1 text-[13px] text-muted-foreground">
                              {m.name}
                            </td>
                            {roles.map((r) => (
                              <Cell key={r.id} role={r} keys={keysOf(r)} value={m.key}
                                inherited={keysOf(r)?.includes(app.app)}
                                onToggle={() => toggle(r, m.key, app.app)} canManage={canManage} />
                            ))}
                          </tr>
                        ))}
                      </Fragment>
                    ))}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1"><ShieldCheck className="h-3 w-3" /> «Полный доступ» правится в карточке роли</span>
          <span className="flex items-center gap-1"><Check className="h-3 w-3 opacity-40" /> бледная галочка — унаследовано от продукта</span>
        </div>
      </CardContent>
    </Card>
  )
}

function Cell({ role, keys, value, onToggle, canManage, inherited, strong }: {
  role: CompanyRole; keys: string[] | null; value: string
  onToggle: () => void; canManage: boolean; inherited?: boolean; strong?: boolean
}) {
  const full = keys === null
  const on = full || inherited || !!keys?.includes(value)
  // Заблокировано: чужая/системная роль, полный доступ (правится карточкой) и раздел,
  // который уже дан вместе с продуктом — снимать его пришлось бы, разбирая продукт.
  const locked = !canManage || role.is_system || full || !!inherited
  return (
    <td className="px-2 py-1 text-center">
      <button type="button" onClick={onToggle} disabled={locked}
        title={full ? 'Полный доступ' : inherited ? 'Дано вместе с продуктом' : undefined}
        className={`inline-flex h-5 w-5 items-center justify-center rounded border transition-colors ${
          on ? 'bg-primary/15 border-primary/50' : 'border-border hover:border-primary/40'
        } ${locked ? 'opacity-50 cursor-default' : 'cursor-pointer'}`}>
        {on && <Check className={`h-3 w-3 ${strong ? 'text-primary' : inherited || full ? 'text-primary/40' : 'text-primary'}`} />}
      </button>
    </td>
  )
}

/** Плашка-сводка прав роли (для карточек и списков). */
export function AccessSummary({ modules }: { modules: string[] | null }) {
  if (modules == null) {
    return <Badge variant="outline" className="text-[10px] gap-1"><ShieldCheck className="h-3 w-3" /> Все модули</Badge>
  }
  const apps = modules.filter((k) => !k.includes(':')).length
  const mods = modules.length - apps
  return (
    <span className="text-[11px] text-muted-foreground">
      продуктов: {apps}{mods ? ` · разделов: ${mods}` : ''}
    </span>
  )
}
