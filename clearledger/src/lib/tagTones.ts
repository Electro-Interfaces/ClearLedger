/**
 * Тона личных тегов. Имя тона хранится на сервере (personal_tags.color), классы —
 * здесь, полными строками: Tailwind собирает только то, что видит в исходнике.
 *
 * Плашка встречи держит текст основным цветом, а тон даёт фон и рамку: так она
 * читается в обеих темах (контраст текста не зависит от выбранного цвета), а цвет
 * не становится единственным носителем — имя тега видно в карточке и подсказке.
 */
export type TagTone = 'slate' | 'blue' | 'teal' | 'green' | 'amber' | 'orange' | 'red' | 'violet'

export const TAG_TONES: { value: TagTone; label: string; dot: string; chip: string; plate: string }[] = [
  { value: 'blue', label: 'Синий', dot: 'bg-blue-500',
    chip: 'border-blue-500/40 bg-blue-500/10', plate: 'border-blue-500/60 bg-blue-500/20 hover:bg-blue-500/30' },
  { value: 'teal', label: 'Бирюзовый', dot: 'bg-teal-500',
    chip: 'border-teal-500/40 bg-teal-500/10', plate: 'border-teal-500/60 bg-teal-500/20 hover:bg-teal-500/30' },
  { value: 'green', label: 'Зелёный', dot: 'bg-emerald-500',
    chip: 'border-emerald-500/40 bg-emerald-500/10', plate: 'border-emerald-500/60 bg-emerald-500/20 hover:bg-emerald-500/30' },
  { value: 'amber', label: 'Жёлтый', dot: 'bg-amber-500',
    chip: 'border-amber-500/40 bg-amber-500/10', plate: 'border-amber-500/60 bg-amber-500/20 hover:bg-amber-500/30' },
  { value: 'orange', label: 'Оранжевый', dot: 'bg-orange-500',
    chip: 'border-orange-500/40 bg-orange-500/10', plate: 'border-orange-500/60 bg-orange-500/20 hover:bg-orange-500/30' },
  { value: 'red', label: 'Красный', dot: 'bg-red-500',
    chip: 'border-red-500/40 bg-red-500/10', plate: 'border-red-500/60 bg-red-500/20 hover:bg-red-500/30' },
  { value: 'violet', label: 'Фиолетовый', dot: 'bg-violet-500',
    chip: 'border-violet-500/40 bg-violet-500/10', plate: 'border-violet-500/60 bg-violet-500/20 hover:bg-violet-500/30' },
  { value: 'slate', label: 'Серый', dot: 'bg-slate-500',
    chip: 'border-slate-500/40 bg-slate-500/10', plate: 'border-slate-500/60 bg-slate-500/20 hover:bg-slate-500/30' },
]

export function tagTone(color: string | null | undefined) {
  return TAG_TONES.find((t) => t.value === color) ?? TAG_TONES[0]
}
