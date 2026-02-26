export type EntryStatus = 'new' | 'recognized' | 'verified' | 'transferred' | 'error'

export interface StatusConfig {
  id: EntryStatus
  label: string
  variant: 'default' | 'secondary' | 'outline' | 'destructive'
  className: string
}

export const statuses: Record<EntryStatus, StatusConfig> = {
  new: {
    id: 'new',
    label: 'Новый',
    variant: 'outline',
    className: 'border-blue-500 text-blue-400',
  },
  recognized: {
    id: 'recognized',
    label: 'Распознан',
    variant: 'outline',
    className: 'border-yellow-500 text-yellow-400',
  },
  verified: {
    id: 'verified',
    label: 'Проверен',
    variant: 'outline',
    className: 'border-green-500 text-green-400',
  },
  transferred: {
    id: 'transferred',
    label: 'Передан',
    variant: 'default',
    className: 'bg-green-600 text-white border-green-600',
  },
  error: {
    id: 'error',
    label: 'Ошибка',
    variant: 'destructive',
    className: '',
  },
}
