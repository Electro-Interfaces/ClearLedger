import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { profiles, type ProfileId } from '@/config/profiles'
import { getCategoriesForProfile, getConnectorTemplates } from '@/config/categories'
import { emptyCustomization } from '@/config/companies'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Plus, Building2, ChevronRight } from 'lucide-react'

const PRESET_COLORS = [
  '#3b82f6',
  '#8b5cf6',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
]

function countEnabledStats(companyId: string, profileId: ProfileId, customizations: Record<string, import('@/config/companies').CompanyCustomization>) {
  const custom = customizations[companyId] ?? emptyCustomization()
  const allCategories = getCategoriesForProfile(profileId)
  const allConnectors = getConnectorTemplates(profileId)

  let categoryCount = 0
  let docTypeCount = 0

  for (const cat of allCategories) {
    if (custom.disabledCategories.includes(cat.id)) continue
    categoryCount++
    for (const sub of cat.subcategories) {
      if (custom.disabledSubcategories.includes(`${cat.id}/${sub.id}`)) continue
      for (const dt of sub.documentTypes) {
        if (!custom.disabledDocTypes.includes(dt.id)) {
          docTypeCount++
        }
      }
    }
  }

  const connectorCount = allConnectors.filter(
    (c) => !custom.disabledConnectors.includes(c.id),
  ).length

  return { categoryCount, docTypeCount, connectorCount }
}

export function CompaniesPage() {
  const { companies, customizations, addCompany } = useCompany()
  const navigate = useNavigate()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newShortName, setNewShortName] = useState('')
  const [newInn, setNewInn] = useState('')
  const [newProfileId, setNewProfileId] = useState<ProfileId>('general')
  const [newColor, setNewColor] = useState(PRESET_COLORS[0])

  function resetForm() {
    setNewName('')
    setNewShortName('')
    setNewInn('')
    setNewProfileId('general')
    setNewColor(PRESET_COLORS[0])
  }

  function handleCreate() {
    if (!newName.trim() || !newShortName.trim()) return

    const id = Date.now().toString(36)
    addCompany({
      id,
      name: newName.trim(),
      shortName: newShortName.trim(),
      inn: newInn.trim() || undefined,
      color: newColor,
      profileId: newProfileId,
    })
    setDialogOpen(false)
    resetForm()
    navigate(`/settings/companies/${id}`)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Компании</h1>
        <Button onClick={() => setDialogOpen(true)}>
          <Plus />
          Добавить компанию
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {companies.map((company) => {
          const profile = profiles[company.profileId]
          const stats = countEnabledStats(company.id, company.profileId, customizations)

          return (
            <Link
              key={company.id}
              to={`/settings/companies/${company.id}`}
              className="block group"
            >
              <Card className="transition-shadow hover:shadow-md h-full">
                <CardContent className="space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className="size-3 rounded-full shrink-0"
                        style={{ backgroundColor: company.color }}
                      />
                      <div className="min-w-0">
                        <div className="font-semibold truncate">{company.name}</div>
                        <div className="text-sm text-muted-foreground truncate">
                          {company.shortName}
                          {company.inn && <span className="ml-2">ИНН {company.inn}</span>}
                        </div>
                      </div>
                    </div>
                    <ChevronRight className="size-5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5" />
                  </div>

                  <Badge variant="secondary">{profile?.label ?? 'Общий'}</Badge>

                  <div className="flex gap-4 text-xs text-muted-foreground">
                    <span>{stats.categoryCount} категор.</span>
                    <span>{stats.docTypeCount} типов док.</span>
                    <span>{stats.connectorCount} коннект.</span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          )
        })}
      </div>

      {/* Диалог создания компании */}
      <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) resetForm() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новая компания</DialogTitle>
            <DialogDescription>
              Создайте компанию и выберите профиль деятельности
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Название *</Label>
              <Input
                placeholder="ООО «Компания»"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label>Короткое название *</Label>
              <Input
                placeholder="Компания"
                value={newShortName}
                onChange={(e) => setNewShortName(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label>ИНН</Label>
              <Input
                placeholder="1234567890"
                value={newInn}
                onChange={(e) => setNewInn(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label>Профиль деятельности</Label>
              <Select value={newProfileId} onValueChange={(v) => setNewProfileId(v as ProfileId)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(profiles).map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.label} — {p.description}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Цвет</Label>
              <div className="flex gap-2">
                {PRESET_COLORS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    className="size-8 rounded-full border-2 transition-all hover:scale-110"
                    style={{
                      backgroundColor: color,
                      borderColor: newColor === color ? 'var(--foreground)' : 'transparent',
                    }}
                    onClick={() => setNewColor(color)}
                  />
                ))}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => { setDialogOpen(false); resetForm() }}>
              Отмена
            </Button>
            <Button onClick={handleCreate} disabled={!newName.trim() || !newShortName.trim()}>
              <Building2 />
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
