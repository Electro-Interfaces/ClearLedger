/**
 * Организация пространства — с чьими данными сейчас работают.
 *
 * 🔴 Стоит в шапке ВСЕГДА, даже когда организация одна (решение МАГа 15.08.2026).
 *
 * Раньше при единственной организации переключатель скрывался — «выбирать не из чего».
 * На деле это оставляло человека без ответа на вопрос «а с кем я сейчас работаю»: он
 * искал глазами привычное место и не находил ничего. Показать одну организацию — не
 * лишний элемент, а подпись к экрану; выбор из одного пункта никому не мешает, а с
 * появлением второго клиента место уже знакомо.
 */
import { useCompany } from '@/contexts/CompanyContext'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function CompanySelector() {
  const { companyId, setCompanyId, companies } = useCompany()

  if (!companies.length) return null

  return (
    <Select value={companyId} onValueChange={setCompanyId}>
      {/* w-full+max-w вместо жёсткой ширины: на мобиле узкий центр шапки —
          фиксированные 200px не ужимались и наезжали на логотип/тему */}
      <SelectTrigger
        className="h-10 w-full min-w-[112px] max-w-[200px] text-sm font-medium bg-secondary border-border [&>span]:truncate"
      >
        <SelectValue placeholder="Организация" />
      </SelectTrigger>
      <SelectContent
        style={{ boxShadow: 'var(--shadow-large)' }}
      >
        {companies.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            <div className="flex items-center gap-2">
              <div
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: c.color }}
              />
              <span>{c.name}</span>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
