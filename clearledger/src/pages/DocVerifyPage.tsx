import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileSearch, LockKeyhole } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { get } from '@/services/apiClient'

interface VerificationResult {
  record_status: 'registered' | 'cancelled' | 'restricted'
  organization?: { name: string; inn: string; kpp: string | null } | null
  kind?: string
  reg_number?: string
  reg_date?: string | null
  document_status?: string
  current_revision?: number
  files?: Array<{ role: string; revision: number; algorithm: string; sha256: string }>
  signature_status?: 'not_checked'
  checked_at: string
  message?: string
  disclaimer: string
}

const STATUS: Record<string, string> = {
  draft: 'черновик', registered: 'зарегистрирован', in_force: 'действует',
  executed: 'исполнен', archived: 'в архиве', cancelled: 'отменён',
}

const FILE_ROLE: Record<string, string> = {
  body: 'Документ', appendix: 'Приложение', signed_scan: 'Подписанный экземпляр',
  attachment: 'Вложение',
}

export function DocVerifyPage() {
  const { token = '' } = useParams()
  const query = useQuery({
    queryKey: ['doc-verification', token],
    queryFn: () => get<VerificationResult>(`/api/doc-share/verify/${token}`),
    retry: false,
  })

  if (query.isLoading) return <Centered>Проверяем запись…</Centered>
  if (query.isError || !query.data) {
    return (
      <Centered>
        <Card className="max-w-md space-y-2 p-6 text-center">
          <FileSearch className="mx-auto h-8 w-8 text-muted-foreground" />
          <h1 className="font-semibold">Запись не найдена</h1>
          <p className="text-sm text-muted-foreground">
            Проверьте адрес и официальный домен, затем отсканируйте код ещё раз.
          </p>
        </Card>
      </Centered>
    )
  }

  const result = query.data
  if (result.record_status === 'restricted') {
    return (
      <Centered>
        <Card className="max-w-md space-y-3 p-6 text-center">
          <LockKeyhole className="mx-auto h-8 w-8 text-muted-foreground" />
          <h1 className="font-semibold">Доступ к сведениям ограничен</h1>
          <p className="text-sm text-muted-foreground">{result.message}</p>
          <Boundary text={result.disclaimer} />
        </Card>
      </Centered>
    )
  }

  const cancelled = result.record_status === 'cancelled'
  return (
    <main className="mx-auto min-h-screen max-w-2xl px-4 py-8 md:py-12">
      <Card className="overflow-hidden">
        <div className={`flex items-start gap-3 border-b p-5 ${cancelled
          ? 'border-destructive/30 bg-destructive/5'
          : 'border-emerald-600/20 bg-emerald-600/5'}`} role="status">
          {cancelled
            ? <AlertTriangle className="mt-0.5 h-6 w-6 shrink-0 text-destructive" />
            : <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald-700" />}
          <div>
            <h1 className="font-semibold">
              {cancelled ? 'Документ отменён' : 'Запись найдена в реестре'}
            </h1>
            <p className="pt-1 text-sm text-muted-foreground">
              Проверено {formatDateTime(result.checked_at)}
            </p>
          </div>
        </div>

        <dl className="grid gap-px bg-border sm:grid-cols-2">
          <Fact label="Организация" value={result.organization?.name || 'не указана'} />
          <Fact label="ИНН / КПП" value={[
            result.organization?.inn, result.organization?.kpp,
          ].filter(Boolean).join(' / ') || 'не указаны'} />
          <Fact label="Документ" value={`${result.reg_number || 'без номера'}${
            result.reg_date ? ` от ${result.reg_date}` : ''}`} />
          <Fact label="Вид" value={result.kind || 'не указан'} />
          <Fact label="Состояние" value={STATUS[result.document_status || ''] || 'не указано'} />
          <Fact label="Текущая редакция" value={String(result.current_revision || 'файл не приложен')} />
        </dl>

        <section className="space-y-3 p-5" aria-labelledby="hashes-heading">
          <div>
            <h2 id="hashes-heading" className="text-sm font-semibold">Контрольные суммы файлов</h2>
            <p className="pt-0.5 text-xs text-muted-foreground">
              SHA-256 позволяет сравнить электронные байты, но сам по себе не является подписью.
            </p>
          </div>
          {(result.files ?? []).length ? (result.files ?? []).map((file) => (
            <div key={`${file.role}-${file.revision}`}
              className="rounded-md border border-border p-3">
              <div className="text-xs text-muted-foreground">
                {FILE_ROLE[file.role] || file.role} · редакция {file.revision} · {file.algorithm}
              </div>
              <div className="break-all pt-1 font-mono text-xs">{file.sha256}</div>
            </div>
          )) : <p className="text-sm text-muted-foreground">Файлы в записи не опубликованы.</p>}
        </section>

        <div className="border-t p-5"><Boundary text={result.disclaimer} /></div>
      </Card>
    </main>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-card p-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="pt-1 text-sm font-medium">{value}</dd>
    </div>
  )
}

function Boundary({ text }: { text: string }) {
  return <p className="text-xs leading-5 text-muted-foreground">{text}</p>
}

function Centered({ children }: { children: React.ReactNode }) {
  return <main className="flex min-h-screen items-center justify-center px-4">{children}</main>
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Moscow',
  }).format(date)
}

export default DocVerifyPage
