/**
 * Документ по ссылке — страница для контрагента, у которого нет учётки.
 *
 * Третий вход без авторизации, рядом с приглашением и сбросом пароля. Показываем
 * реквизиты, даём скачать файлы и принимаем подтверждение получения. Текст, под
 * которым человек подтверждает, приходит с сервера и хранится вместе с отметкой:
 * через два года спор будет не о факте нажатия, а о том, с чем согласились.
 */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Download, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { get, post } from '@/services/apiClient'

interface SharedDoc {
  title: string
  reg_number: string | null
  reg_date: string | null
  summary: string | null
  recipient_name: string | null
  acknowledged_at: string | null
  ack_text: string
  files: Array<{ id: string; file_name: string; size: number }>
}

export function DocSharePage() {
  const { token = '' } = useParams()
  const [name, setName] = useState('')

  const q = useQuery({
    queryKey: ['doc-share', token],
    queryFn: () => get<SharedDoc>(`/api/doc-share/${token}`),
    retry: false,
  })

  const ack = useMutation({
    mutationFn: () => post<{ acknowledged_at: string }>(
      `/api/doc-share/${token}/ack`, { name: name.trim() }),
    onSuccess: () => q.refetch(),
  })

  if (q.isLoading) {
    return <Centered>Загрузка…</Centered>
  }
  if (q.isError || !q.data) {
    // Одинаковый ответ на «нет», «отозвана» и «истекла»: подсказывать, что
    // ссылка когда-то существовала, незачем.
    return (
      <Centered>
        <div className="text-center">
          <div className="text-base font-medium">Ссылка недействительна</div>
          <div className="pt-1 text-sm text-muted-foreground">
            Срок действия истёк или ссылка отозвана. Запросите новую у отправителя.
          </div>
        </div>
      </Centered>
    )
  }

  const d = q.data

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <Card className="space-y-4 p-6">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            {d.reg_number ? `Документ ${d.reg_number}` : 'Документ'}
            {d.reg_date ? ` от ${d.reg_date}` : ''}
          </div>
          <h1 className="pt-1 text-lg font-semibold">{d.title}</h1>
          {d.recipient_name && (
            <div className="pt-1 text-sm text-muted-foreground">
              Получатель: {d.recipient_name}
            </div>
          )}
        </div>

        {d.summary && <p className="text-sm">{d.summary}</p>}

        <div className="space-y-1.5">
          {d.files.map((f) => (
            <a key={f.id} href={`/api/doc-share/${token}/file/${f.id}`}
              className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm hover:bg-accent/40">
              <span className="flex min-w-0 items-center gap-2">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{f.file_name}</span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                {Math.max(1, Math.round(f.size / 1024))} КБ
                <Download className="h-3.5 w-3.5" />
              </span>
            </a>
          ))}
          {d.files.length === 0 && (
            <div className="text-sm text-muted-foreground">Файлы не приложены</div>
          )}
        </div>

        {d.acknowledged_at ? (
          <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm">
            <CheckCircle2 className="h-4 w-4 text-green-600" />
            Получение подтверждено {d.acknowledged_at.slice(0, 16).replace('T', ' ')}
          </div>
        ) : (
          <div className="space-y-2 border-t border-border pt-4">
            <p className="text-sm">{d.ack_text}</p>
            <div className="flex flex-wrap gap-2">
              <Input value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Фамилия и инициалы" className="h-9 max-w-xs" />
              <Button size="sm" disabled={name.trim().length < 2 || ack.isPending}
                onClick={() => ack.mutate()}>
                Подтвердить получение
              </Button>
            </div>
            {ack.isError && (
              <p className="text-xs text-destructive">
                Не отправилось: {(ack.error as Error).message}
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 text-sm text-muted-foreground">
      {children}
    </div>
  )
}

export default DocSharePage
