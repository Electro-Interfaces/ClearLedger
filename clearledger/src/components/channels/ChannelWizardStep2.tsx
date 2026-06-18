import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { X } from 'lucide-react'
import type { ChannelTemplate, SetupField } from '@/types/channel'

interface Props {
  template: ChannelTemplate
  channelName: string
  onChannelNameChange: (name: string) => void
  values: Record<string, string>
  onValueChange: (key: string, value: string) => void
}

function TagsInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [input, setInput] = useState('')
  const tags = value ? value.split(',').filter(Boolean) : []

  function addTag() {
    const trimmed = input.trim()
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed].join(','))
    }
    setInput('')
  }

  function removeTag(tag: string) {
    onChange(tags.filter((t) => t !== tag).join(','))
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {tags.map((tag) => (
          <Badge key={tag} variant="secondary" className="gap-1 pl-2 pr-1">
            {tag}
            <button onClick={() => removeTag(tag)} className="h-4 w-4 flex items-center justify-center rounded-full hover:bg-destructive/20">
              <X className="h-2.5 w-2.5" />
            </button>
          </Badge>
        ))}
      </div>
      <Input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
        placeholder={placeholder}
      />
    </div>
  )
}

function FieldInput({ field, value, onChange }: { field: SetupField; value: string; onChange: (v: string) => void }) {
  switch (field.type) {
    case 'password':
      return <Input type="password" value={value} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} />
    case 'number':
      return <Input type="number" value={value} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} />
    case 'select':
      return (
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger><SelectValue placeholder="Выберите..." /></SelectTrigger>
          <SelectContent>
            {field.options?.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    case 'tags':
      return <TagsInput value={value} onChange={onChange} placeholder={field.placeholder} />
    default:
      return <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} />
  }
}

export function ChannelWizardStep2({ template, channelName, onChannelNameChange, values, onValueChange }: Props) {
  return (
    <div className="space-y-5">
      <div className="text-xs text-muted-foreground uppercase tracking-wider">
        Подключение: {template.name}
      </div>

      {/* Channel name */}
      <div>
        <Label className="text-sm mb-1.5 block">Название канала</Label>
        <Input value={channelName} onChange={(e) => onChannelNameChange(e.target.value)} placeholder="Например: Смены — АКАЗС Витебский" />
      </div>

      {/* Dynamic fields from template */}
      {template.setupFields.map((field) => (
        <div key={field.key}>
          <Label className="text-sm mb-1.5 block">
            {field.label}
            {field.required && <span className="text-destructive ml-0.5">*</span>}
          </Label>
          <FieldInput
            field={field}
            value={values[field.key] ?? field.defaultValue ?? ''}
            onChange={(v) => onValueChange(field.key, v)}
          />
        </div>
      ))}
    </div>
  )
}
