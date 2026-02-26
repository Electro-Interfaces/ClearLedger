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
      <SelectTrigger
        className="sel h-10 w-[200px] text-sm font-medium"
        style={{
          background: 'hsl(217 32% 15% / 0.6)',
          borderColor: 'hsl(217 32% 25%)',
          color: 'hsl(0 0% 85%)',
        }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="size-2.5 shrink-0 rounded-full"
            style={{ background: company.color }}
          />
          <SelectValue placeholder="Выберите компанию" />
        </div>
      </SelectTrigger>
      <SelectContent
        style={{
          background: 'hsl(215 28% 8%)',
          borderColor: 'hsl(217 32% 20% / 0.5)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.45)',
        }}
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
