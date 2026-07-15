import { useCompany } from '@/contexts/CompanyContext'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Building2 } from 'lucide-react'

export function CompanySelector() {
  const { company, companyId, setCompanyId, companies } = useCompany()

  if (companies.length <= 1) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Building2 className="size-4" />
        <span className="hidden sm:inline">{company.name}</span>
      </div>
    )
  }

  return (
    <Select value={companyId} onValueChange={setCompanyId}>
      {/* w-full+max-w вместо жёсткой ширины: на мобиле узкий центр шапки —
          фиксированные 200px не ужимались и наезжали на логотип/тему */}
      <SelectTrigger
        className="h-10 w-full max-w-[200px] min-w-0 text-sm font-medium bg-secondary border-border [&>span]:truncate"
      >
        <SelectValue placeholder="Выберите компанию" />
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
