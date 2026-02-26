import { useState, useMemo, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { profiles, getProfile, type ProfileId, type Category, type SubCategory, type ConnectorTemplate } from '@/config/profiles'
import { emptyCustomization, type CompanyCustomization } from '@/config/companies'
import { Checkbox } from '@/components/ui/checkbox'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
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
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Building2,
  Trash2,
  AlertTriangle,
  Plug,
  FileText,
  Eye,
  Save,
} from 'lucide-react'

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

// ──────────────────────────────────────────────────────
// Helper: count doc types in a subcategory / category
// ──────────────────────────────────────────────────────

function countDocTypes(cat: Category): number {
  return cat.subcategories.reduce((acc, sub) => acc + sub.documentTypes.length, 0)
}

function countSubDocTypes(sub: SubCategory): number {
  return sub.documentTypes.length
}

// ──────────────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────────────

export function CompanyEditPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const {
    companies,
    customizations,
    updateCompany,
    updateCustomization,
    removeCompany,
  } = useCompany()

  const company = companies.find((c) => c.id === id)

  // ── Company info form state ──
  const [editName, setEditName] = useState(company?.name ?? '')
  const [editShortName, setEditShortName] = useState(company?.shortName ?? '')
  const [editInn, setEditInn] = useState(company?.inn ?? '')
  const [editProfileId, setEditProfileId] = useState<ProfileId>(company?.profileId ?? 'general')
  const [editColor, setEditColor] = useState(company?.color ?? PRESET_COLORS[0])
  const [profileChangeWarning, setProfileChangeWarning] = useState(false)
  const [pendingProfileId, setPendingProfileId] = useState<ProfileId | null>(null)

  // ── Customization state ──
  const existingCustom = (id ? customizations[id] : undefined) ?? emptyCustomization()
  const [disabledCategories, setDisabledCategories] = useState<Set<string>>(new Set(existingCustom.disabledCategories))
  const [disabledSubcategories, setDisabledSubcategories] = useState<Set<string>>(new Set(existingCustom.disabledSubcategories))
  const [disabledDocTypes, setDisabledDocTypes] = useState<Set<string>>(new Set(existingCustom.disabledDocTypes))
  const [disabledConnectors, setDisabledConnectors] = useState<Set<string>>(new Set(existingCustom.disabledConnectors))

  // ── Expanded state for categories ──
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())

  // ── Delete dialog ──
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  // ── Profile data ──
  const profile = useMemo(() => getProfile(editProfileId), [editProfileId])
  const allCategories = profile.categories
  const allConnectors = profile.connectorTemplates

  // ──────────────────────────────────────────────
  // Handlers: Company info
  // ──────────────────────────────────────────────

  function handleProfileChange(newProfileId: ProfileId) {
    if (newProfileId !== editProfileId) {
      setPendingProfileId(newProfileId)
      setProfileChangeWarning(true)
    }
  }

  function confirmProfileChange() {
    if (pendingProfileId) {
      setEditProfileId(pendingProfileId)
      // Reset customization when profile changes
      setDisabledCategories(new Set())
      setDisabledSubcategories(new Set())
      setDisabledDocTypes(new Set())
      setDisabledConnectors(new Set())
    }
    setPendingProfileId(null)
    setProfileChangeWarning(false)
  }

  function handleSaveInfo() {
    if (!id || !editName.trim() || !editShortName.trim()) return
    updateCompany(id, {
      name: editName.trim(),
      shortName: editShortName.trim(),
      inn: editInn.trim() || undefined,
      profileId: editProfileId,
      color: editColor,
    })
  }

  // ──────────────────────────────────────────────
  // Handlers: Category tree checkboxes
  // ──────────────────────────────────────────────

  const toggleCategory = useCallback((cat: Category) => {
    const isDisabled = disabledCategories.has(cat.id)
    if (isDisabled) {
      // Enable: remove from disabled
      setDisabledCategories((prev) => { const next = new Set(prev); next.delete(cat.id); return next })
      // Also re-enable all subcategories and doc types under this category
      setDisabledSubcategories((prev) => {
        const next = new Set(prev)
        for (const sub of cat.subcategories) next.delete(`${cat.id}/${sub.id}`)
        return next
      })
      setDisabledDocTypes((prev) => {
        const next = new Set(prev)
        for (const sub of cat.subcategories) {
          for (const dt of sub.documentTypes) next.delete(dt.id)
        }
        return next
      })
    } else {
      // Disable: add to disabled
      setDisabledCategories((prev) => new Set(prev).add(cat.id))
    }
  }, [disabledCategories])

  const toggleSubcategory = useCallback((cat: Category, sub: SubCategory) => {
    const key = `${cat.id}/${sub.id}`
    const isDisabled = disabledSubcategories.has(key)
    if (isDisabled) {
      // Enable subcategory
      setDisabledSubcategories((prev) => { const next = new Set(prev); next.delete(key); return next })
      // Re-enable all doc types under it
      setDisabledDocTypes((prev) => {
        const next = new Set(prev)
        for (const dt of sub.documentTypes) next.delete(dt.id)
        return next
      })
      // Also ensure parent category is enabled
      setDisabledCategories((prev) => { const next = new Set(prev); next.delete(cat.id); return next })
    } else {
      // Disable subcategory
      setDisabledSubcategories((prev) => new Set(prev).add(key))
      // Check if all subcategories are now disabled -> disable parent
      const allSubsDisabled = cat.subcategories.every(
        (s) => s.id === sub.id || disabledSubcategories.has(`${cat.id}/${s.id}`),
      )
      if (allSubsDisabled) {
        setDisabledCategories((prev) => new Set(prev).add(cat.id))
      }
    }
  }, [disabledSubcategories])

  const toggleDocType = useCallback((cat: Category, sub: SubCategory, dtId: string) => {
    const isDisabled = disabledDocTypes.has(dtId)
    if (isDisabled) {
      // Enable doc type
      setDisabledDocTypes((prev) => { const next = new Set(prev); next.delete(dtId); return next })
      // Ensure parent subcategory and category are enabled
      setDisabledSubcategories((prev) => { const next = new Set(prev); next.delete(`${cat.id}/${sub.id}`); return next })
      setDisabledCategories((prev) => { const next = new Set(prev); next.delete(cat.id); return next })
    } else {
      // Disable doc type
      setDisabledDocTypes((prev) => new Set(prev).add(dtId))
      // Check if all doc types in subcategory are disabled -> disable subcategory
      const allDtDisabled = sub.documentTypes.every(
        (d) => d.id === dtId || disabledDocTypes.has(d.id),
      )
      if (allDtDisabled) {
        const subKey = `${cat.id}/${sub.id}`
        setDisabledSubcategories((prev) => new Set(prev).add(subKey))
        // Check if all subcategories are disabled -> disable category
        const allSubsDisabled = cat.subcategories.every(
          (s) => s.id === sub.id || disabledSubcategories.has(`${cat.id}/${s.id}`),
        )
        if (allSubsDisabled) {
          setDisabledCategories((prev) => new Set(prev).add(cat.id))
        }
      }
    }
  }, [disabledDocTypes, disabledSubcategories])

  // ──────────────────────────────────────────────
  // Handlers: Connectors
  // ──────────────────────────────────────────────

  const toggleConnector = useCallback((connectorId: string) => {
    setDisabledConnectors((prev) => {
      const next = new Set(prev)
      if (next.has(connectorId)) next.delete(connectorId)
      else next.add(connectorId)
      return next
    })
  }, [])

  // ──────────────────────────────────────────────
  // Checked state helpers
  // ──────────────────────────────────────────────

  function isCategoryChecked(cat: Category): boolean | 'indeterminate' {
    if (disabledCategories.has(cat.id)) return false
    // Check if all children are enabled
    let allEnabled = true
    let someEnabled = false
    for (const sub of cat.subcategories) {
      const subKey = `${cat.id}/${sub.id}`
      if (disabledSubcategories.has(subKey)) {
        allEnabled = false
        continue
      }
      for (const dt of sub.documentTypes) {
        if (disabledDocTypes.has(dt.id)) {
          allEnabled = false
        } else {
          someEnabled = true
        }
      }
      if (sub.documentTypes.length > 0 && sub.documentTypes.every((dt) => disabledDocTypes.has(dt.id))) {
        allEnabled = false
      } else if (sub.documentTypes.some((dt) => !disabledDocTypes.has(dt.id))) {
        someEnabled = true
      }
    }
    if (allEnabled) return true
    if (someEnabled) return 'indeterminate'
    return false
  }

  function isSubcategoryChecked(cat: Category, sub: SubCategory): boolean | 'indeterminate' {
    if (disabledCategories.has(cat.id)) return false
    const subKey = `${cat.id}/${sub.id}`
    if (disabledSubcategories.has(subKey)) return false

    const enabledCount = sub.documentTypes.filter((dt) => !disabledDocTypes.has(dt.id)).length
    if (enabledCount === sub.documentTypes.length) return true
    if (enabledCount > 0) return 'indeterminate'
    return false
  }

  function isDocTypeChecked(cat: Category, sub: SubCategory, dtId: string): boolean {
    if (disabledCategories.has(cat.id)) return false
    if (disabledSubcategories.has(`${cat.id}/${sub.id}`)) return false
    return !disabledDocTypes.has(dtId)
  }

  function countEnabledDocTypes(cat: Category): number {
    if (disabledCategories.has(cat.id)) return 0
    let count = 0
    for (const sub of cat.subcategories) {
      if (disabledSubcategories.has(`${cat.id}/${sub.id}`)) continue
      for (const dt of sub.documentTypes) {
        if (!disabledDocTypes.has(dt.id)) count++
      }
    }
    return count
  }

  function countEnabledSubDocTypes(cat: Category, sub: SubCategory): number {
    if (disabledCategories.has(cat.id)) return 0
    if (disabledSubcategories.has(`${cat.id}/${sub.id}`)) return 0
    return sub.documentTypes.filter((dt) => !disabledDocTypes.has(dt.id)).length
  }

  // ──────────────────────────────────────────────
  // Save customization
  // ──────────────────────────────────────────────

  function handleSaveCustomization() {
    if (!id) return
    const customization: CompanyCustomization = {
      disabledCategories: Array.from(disabledCategories),
      disabledSubcategories: Array.from(disabledSubcategories),
      disabledDocTypes: Array.from(disabledDocTypes),
      disabledConnectors: Array.from(disabledConnectors),
    }
    updateCustomization(id, customization)
  }

  // ──────────────────────────────────────────────
  // Delete
  // ──────────────────────────────────────────────

  function handleDelete() {
    if (!id) return
    removeCompany(id)
    navigate('/settings/companies')
  }

  const canDelete = companies.length > 1

  // ──────────────────────────────────────────────
  // Toggle expand
  // ──────────────────────────────────────────────

  function toggleExpand(catId: string) {
    setExpandedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(catId)) next.delete(catId)
      else next.add(catId)
      return next
    })
  }

  // ──────────────────────────────────────────────
  // Not found
  // ──────────────────────────────────────────────

  if (!company) {
    return (
      <div className="space-y-6">
        <Link to="/settings/companies" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" />
          Назад к списку
        </Link>
        <div className="text-center py-12">
          <Building2 className="size-12 mx-auto text-muted-foreground mb-4" />
          <h2 className="text-xl font-semibold">Компания не найдена</h2>
          <p className="text-muted-foreground mt-2">Компания с указанным идентификатором не существует</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* ── Back link ── */}
      <Link
        to="/settings/companies"
        className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Назад к списку компаний
      </Link>

      {/* ── Page header ── */}
      <div className="flex items-center gap-3">
        <div
          className="size-4 rounded-full shrink-0"
          style={{ backgroundColor: editColor }}
        />
        <h1 className="text-2xl font-bold">{editName || company.name}</h1>
        <Badge variant="secondary">{profile.label}</Badge>
      </div>

      {/* ═══════════════════════════════════════════ */}
      {/* Section A: Company Info                     */}
      {/* ═══════════════════════════════════════════ */}
      <Card>
        <CardHeader>
          <CardTitle>Информация о компании</CardTitle>
          <CardDescription>Основные реквизиты и профиль деятельности</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Название</Label>
              <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Короткое название</Label>
              <Input value={editShortName} onChange={(e) => setEditShortName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>ИНН</Label>
              <Input value={editInn} onChange={(e) => setEditInn(e.target.value)} placeholder="1234567890" />
            </div>
            <div className="space-y-2">
              <Label>Профиль деятельности</Label>
              <Select value={editProfileId} onValueChange={(v) => handleProfileChange(v as ProfileId)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(profiles).map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
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
                    borderColor: editColor === color ? 'var(--foreground)' : 'transparent',
                  }}
                  onClick={() => setEditColor(color)}
                />
              ))}
            </div>
          </div>

          <Button onClick={handleSaveInfo} disabled={!editName.trim() || !editShortName.trim()}>
            <Save />
            Сохранить информацию
          </Button>
        </CardContent>
      </Card>

      {/* ═══════════════════════════════════════════ */}
      {/* Section B: Profile Customization            */}
      {/* ═══════════════════════════════════════════ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="size-5" />
            Категории и типы документов
          </CardTitle>
          <CardDescription>
            Отключите ненужные категории, подкатегории и типы документов для этой компании.
            Профиль: {profile.label} ({profile.description})
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {allCategories.map((cat) => {
            const isExpanded = expandedCategories.has(cat.id)
            const catChecked = isCategoryChecked(cat)
            const enabledCount = countEnabledDocTypes(cat)
            const totalCount = countDocTypes(cat)

            return (
              <div key={cat.id} className="border rounded-lg">
                {/* Category header */}
                <div className="flex items-center gap-2 px-3 py-2.5 hover:bg-muted/50 transition-colors">
                  <Checkbox
                    checked={catChecked}
                    onCheckedChange={() => toggleCategory(cat)}
                  />
                  <button
                    type="button"
                    className="flex items-center gap-2 flex-1 min-w-0 text-left"
                    onClick={() => toggleExpand(cat.id)}
                  >
                    {isExpanded
                      ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
                      : <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                    }
                    <span className="font-medium truncate">{cat.label}</span>
                    <Badge variant="outline" className="ml-auto shrink-0 text-xs">
                      {enabledCount}/{totalCount}
                    </Badge>
                  </button>
                </div>

                {/* Subcategories (expanded) */}
                {isExpanded && (
                  <div className="border-t">
                    {cat.subcategories.map((sub) => {
                      const subChecked = isSubcategoryChecked(cat, sub)
                      const subEnabledCount = countEnabledSubDocTypes(cat, sub)
                      const subTotalCount = countSubDocTypes(sub)

                      return (
                        <div key={sub.id}>
                          {/* Subcategory header */}
                          <div className="flex items-center gap-2 pl-10 pr-3 py-2 hover:bg-muted/30 transition-colors">
                            <Checkbox
                              checked={subChecked}
                              onCheckedChange={() => toggleSubcategory(cat, sub)}
                            />
                            <span className="text-sm flex-1 min-w-0 truncate">{sub.label}</span>
                            <Badge variant="outline" className="shrink-0 text-xs">
                              {subEnabledCount}/{subTotalCount}
                            </Badge>
                          </div>

                          {/* Document types */}
                          {sub.documentTypes.map((dt) => {
                            const dtChecked = isDocTypeChecked(cat, sub, dt.id)

                            return (
                              <div
                                key={dt.id}
                                className="flex items-center gap-2 pl-16 pr-3 py-1.5 hover:bg-muted/20 transition-colors"
                              >
                                <Checkbox
                                  checked={dtChecked}
                                  onCheckedChange={() => toggleDocType(cat, sub, dt.id)}
                                />
                                <span className="text-sm text-muted-foreground flex-1 min-w-0 truncate">
                                  {dt.label}
                                </span>
                                {dt.ocrEnabled && (
                                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                                    <Eye className="size-3 mr-0.5" />
                                    OCR
                                  </Badge>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* ═══════════════════════════════════════════ */}
      {/* Section C: Connector Templates              */}
      {/* ═══════════════════════════════════════════ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plug className="size-5" />
            Шаблоны коннекторов
          </CardTitle>
          <CardDescription>
            Выберите доступные коннекторы для интеграции
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {allConnectors.map((connector) => {
            const isEnabled = !disabledConnectors.has(connector.id)

            return (
              <div
                key={connector.id}
                className="flex items-center gap-3 px-3 py-2.5 border rounded-lg hover:bg-muted/30 transition-colors"
              >
                <Checkbox
                  checked={isEnabled}
                  onCheckedChange={() => toggleConnector(connector.id)}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{connector.name}</div>
                  <div className="text-xs text-muted-foreground">{connector.description}</div>
                </div>
                <Badge variant="outline" className="shrink-0 text-xs">
                  {connector.type}
                </Badge>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* ── Save customization ── */}
      <div className="flex justify-end">
        <Button size="lg" onClick={handleSaveCustomization}>
          <Save />
          Сохранить настройки профиля
        </Button>
      </div>

      <Separator />

      {/* ═══════════════════════════════════════════ */}
      {/* Danger zone: Delete                         */}
      {/* ═══════════════════════════════════════════ */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive flex items-center gap-2">
            <AlertTriangle className="size-5" />
            Опасная зона
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Удалить компанию</p>
              <p className="text-sm text-muted-foreground">
                {canDelete
                  ? 'Компания и все её настройки будут удалены. Это действие необратимо.'
                  : 'Невозможно удалить единственную компанию.'}
              </p>
            </div>
            <Button
              variant="destructive"
              disabled={!canDelete}
              onClick={() => setDeleteDialogOpen(true)}
            >
              <Trash2 />
              Удалить
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ── Profile change warning dialog ── */}
      <Dialog open={profileChangeWarning} onOpenChange={setProfileChangeWarning}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" />
              Изменение профиля
            </DialogTitle>
            <DialogDescription>
              При смене профиля деятельности все текущие настройки кастомизации (отключённые категории,
              подкатегории, типы документов и коннекторы) будут сброшены. Продолжить?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProfileChangeWarning(false)}>
              Отмена
            </Button>
            <Button onClick={confirmProfileChange}>
              Сменить профиль
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete confirmation dialog ── */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Trash2 className="size-5 text-destructive" />
              Удалить компанию
            </DialogTitle>
            <DialogDescription>
              Вы уверены, что хотите удалить компанию «{company.name}»? Все настройки профиля
              и кастомизации будут потеряны. Это действие нельзя отменить.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Отмена
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              <Trash2 />
              Удалить безвозвратно
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
