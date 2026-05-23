import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Loader2, CheckCircle2, XCircle } from 'lucide-react'
import { ChannelScheduleForm } from './ChannelScheduleForm'
import { stsLogin, stsGetShifts } from '@/services/fuel/stsApiClient'
import type { ScheduleConfig } from '@/types/channel'

interface Props {
  schedule: ScheduleConfig
  onScheduleChange: (schedule: ScheduleConfig) => void
  connectionValues: Record<string, string>
}

export function ChannelWizardStep3({ schedule, onScheduleChange, connectionValues }: Props) {
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const login = connectionValues.login ?? ''
      const password = connectionValues.password ?? ''
      const systemCode = Number(connectionValues.systemCode ?? '65')
      const url = connectionValues.url ?? undefined

      const token = await stsLogin(url, login, password)
      if (!token) throw new Error('Авторизация не удалась')

      const shifts = await stsGetShifts(systemCode)
      setTestResult({ ok: true, message: `Подключено, найдено ${shifts.length} смен` })
    } catch (err) {
      setTestResult({ ok: false, message: err instanceof Error ? err.message : 'Ошибка подключения' })
    } finally {
      setTesting(false)
    }
  }

  const hasCredentials = connectionValues.login && connectionValues.password

  return (
    <div className="space-y-6">
      <div className="text-xs text-muted-foreground uppercase tracking-wider">Расписание загрузки</div>

      <ChannelScheduleForm config={schedule} onChange={onScheduleChange} />

      {/* Test connection */}
      {hasCredentials && (
        <div className="pt-2 border-t border-border/40">
          <Button variant="outline" onClick={handleTest} disabled={testing} className="w-full">
            {testing ? (
              <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Проверка...</>
            ) : (
              'Проверить подключение'
            )}
          </Button>
          {testResult && (
            <div className={`flex items-center gap-2 mt-3 text-sm ${testResult.ok ? 'text-emerald-600' : 'text-destructive'}`}>
              {testResult.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              {testResult.message}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
