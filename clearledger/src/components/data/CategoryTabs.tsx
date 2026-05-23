import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getSubcategories } from '@/config/categories'
import { useCompany } from '@/contexts/CompanyContext'

interface CategoryTabsProps {
  categoryId: string
  activeSubcategory: string
  onSubcategoryChange: (value: string) => void
}

export function CategoryTabs({ categoryId, activeSubcategory, onSubcategoryChange }: CategoryTabsProps) {
  const { company } = useCompany()
  const subcategories = getSubcategories(company.profileId, categoryId)

  if (subcategories.length === 0) return null

  return (
    <Tabs value={activeSubcategory} onValueChange={onSubcategoryChange}>
      <TabsList>
        <TabsTrigger value="all">Все</TabsTrigger>
        {subcategories.map((sub) => (
          <TabsTrigger key={sub.id} value={sub.id}>
            {sub.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}
