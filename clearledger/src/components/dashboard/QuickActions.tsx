import { Upload, PenLine, Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const actions = [
  { label: 'Загрузить файлы', icon: Upload, path: '/input' },
  { label: 'Ручная запись', icon: PenLine, path: '/input/manual' },
  { label: 'Поиск', icon: Search, path: '/search' },
]

export function QuickActions() {
  const navigate = useNavigate()

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader>
        <CardTitle>Быстрые действия</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {actions.map((action) => {
          const Icon = action.icon
          return (
            <Button
              key={action.path}
              variant="outline"
              className="w-full justify-start gap-3"
              onClick={() => navigate(action.path)}
            >
              <Icon className="h-4 w-4" />
              {action.label}
            </Button>
          )
        })}
      </CardContent>
    </Card>
  )
}
