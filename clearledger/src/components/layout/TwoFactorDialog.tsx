/**
 * Двухэтапный вход (TOTP): включить или отключить второй фактор (аудит 07.10.2026).
 *
 * С ним утёкший пароль без телефона владельца входа не даёт. Ключ показывается текстом
 * и ссылкой otpauth:// — Google Authenticator, Яндекс Ключ и Microsoft Authenticator
 * принимают ручной ввод ключа; QR-кода нет, чтобы не тянуть генератор ради одного окна.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { twofaDisable, twofaEnable, twofaSetup, twofaStatus } from '@/services/authService'

export function TwoFactorDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['twofa'], queryFn: twofaStatus, enabled: open })
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const enabled = status.data?.enabled ?? false

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      toast.success(ok)
      setSetup(null); setCode('')
      await qc.invalidateQueries({ queryKey: ['twofa'] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не получилось')
    } finally { setBusy(false) }
  }
  const close = (v: boolean) => { if (!v) { setSetup(null); setCode('') } onOpenChange(v) }
  const codeInput = (
    <input inputMode="numeric" autoComplete="one-time-code" maxLength={8} placeholder="Код из приложения, 6 цифр"
      value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
      className="h-9 w-full rounded-md border bg-background px-3 text-sm tracking-widest" />
  )

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Двухэтапный вход</DialogTitle></DialogHeader>
        {status.isLoading ? <p className="text-sm text-muted-foreground">Загрузка…</p>
          : enabled ? (
            <div className="space-y-3 text-sm">
              <p>Включён: при входе после пароля спрашивается код из приложения на телефоне.</p>
              <p className="text-xs text-muted-foreground">Чтобы отключить, введите действующий код.</p>
              {codeInput}
              <Button variant="outline" disabled={busy || code.length < 6}
                onClick={() => void run(() => twofaDisable(code), 'Двухэтапный вход отключён')}>Отключить</Button>
            </div>
          ) : !setup ? (
            <div className="space-y-3 text-sm">
              <p>С двухэтапным входом пароля мало: нужен ещё код из приложения на вашем телефоне. Если пароль утечёт,
                без телефона в учётную запись не войти.</p>
              <p className="text-xs text-muted-foreground">Понадобится приложение-аутентификатор: Яндекс Ключ, Google Authenticator
                или Microsoft Authenticator.</p>
              <Button disabled={busy} onClick={() => void (async () => {
                setBusy(true)
                try { setSetup(await twofaSetup()) } catch (e) { toast.error(e instanceof Error ? e.message : 'Не получилось') }
                finally { setBusy(false) }
              })()}>Включить</Button>
            </div>
          ) : (
            <div className="space-y-3 text-sm">
              <p>1. В приложении-аутентификаторе добавьте запись вручную и введите ключ:</p>
              <code className="block select-all break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm tracking-wider">
                {setup.secret.match(/.{1,4}/g)?.join(' ')}
              </code>
              <p className="text-xs text-muted-foreground">С телефона можно открыть ссылку — приложение заведёт запись само:{' '}
                <a className="text-primary underline break-all" href={setup.uri}>добавить в приложение</a></p>
              <p>2. Введите код, который показывает приложение:</p>
              {codeInput}
              <Button disabled={busy || code.length < 6}
                onClick={() => void run(() => twofaEnable(code), 'Двухэтапный вход включён')}>Подтвердить и включить</Button>
            </div>
          )}
      </DialogContent>
    </Dialog>
  )
}
