import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import {
  managedConnectorService,
  type MangoDirectory,
} from '@/services/spaceConnectorsService'

export function MangoDirectoryEditor({
  directory,
  companyId,
  connectorId,
  disabled,
  onUpdated,
  onAddLine,
}: {
  directory: MangoDirectory
  companyId: string
  connectorId: string
  disabled: boolean
  onUpdated: () => Promise<void>
  onAddLine: (number: string) => void
}) {
  const users = directory.entries.filter((row) => row.kind === 'user')
  return (
    <div className="space-y-3 border-t pt-4">
      <h3 className="text-sm font-medium">Сотрудники и линии Mango</h3>
      {!directory.synced_at ? (
        <p className="text-sm text-muted-foreground">
          Нажмите «Обновить справочники Mango», чтобы выбрать линии и
          сопоставить сотрудников.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Справочники обновлены{' '}
          {new Date(directory.synced_at).toLocaleString('ru-RU')}
        </p>
      )}
      {directory.entries
        .filter((row) => row.kind === 'line')
        .map((row) => (
          <div
            key={row.external_id}
            className="flex flex-wrap items-center justify-between gap-2 text-sm"
          >
            <span>
              {row.name} · {row.extension}
            </span>
            {/^\+?\d{7,15}$/.test(row.extension) && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled}
                onClick={() => onAddLine(row.extension)}
              >
                Добавить в наши линии
              </Button>
            )}
          </div>
        ))}
      {users.map((row) => (
        <OperatorBinding
          key={`${row.external_id}:${directory.bindings.find((item) => item.extension === row.extension)?.user_id || ''}`}
          row={row}
          directory={directory}
          companyId={companyId}
          connectorId={connectorId}
          disabled={disabled}
          onUpdated={onUpdated}
        />
      ))}
    </div>
  )
}

function OperatorBinding({
  row,
  directory,
  companyId,
  connectorId,
  disabled,
  onUpdated,
}: {
  row: MangoDirectory['entries'][number]
  directory: MangoDirectory
  companyId: string
  connectorId: string
  disabled: boolean
  onUpdated: () => Promise<void>
}) {
  const binding = directory.bindings.find(
    (item) => item.extension === row.extension,
  )
  const [userId, setUserId] = useState(binding?.user_id || '')
  const [canCall, setCanCall] = useState(binding?.can_call || false)
  const save = useMutation({
    mutationFn: () =>
      managedConnectorService.action(
        companyId,
        'support',
        connectorId,
        'bind-operator',
        {
          extension: row.extension,
          user_id: userId || null,
          can_call: canCall,
        },
      ),
    onSuccess: onUpdated,
  })
  const dirty =
    userId !== (binding?.user_id || '') ||
    canCall !== Boolean(binding?.can_call)
  return (
    <div className="space-y-2 rounded-md border p-3">
      <p className="text-sm font-medium">
        {row.name} · {row.extension}
      </p>
      <label className="block space-y-1 text-xs text-muted-foreground">
        <span>Пользователь Поддержки для {row.extension}</span>
        <select
          className="h-11 w-full rounded-md border bg-background px-2 text-sm text-foreground"
          value={userId}
          disabled={disabled || save.isPending}
          onChange={(event) => {
            setUserId(event.target.value)
            save.reset()
          }}
        >
          <option value="">Не сопоставлен</option>
          {directory.staff.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name} · {user.email}
            </option>
          ))}
        </select>
      </label>
      <label className="flex min-h-11 items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={canCall}
          disabled={disabled || save.isPending || !userId}
          onChange={(event) => {
            setCanCall(event.target.checked)
            save.reset()
          }}
        />
        Разрешить исходящие с номера {row.extension}
      </label>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || save.isPending || !dirty}
        onClick={() => save.mutate()}
      >
        Сохранить сопоставление {row.extension}
      </Button>
      {save.error && (
        <p role="alert" className="text-sm text-destructive">
          {save.error.message}
        </p>
      )}
      {save.isSuccess && (
        <p role="status" className="text-sm text-muted-foreground">
          Сопоставление сохранено
        </p>
      )}
    </div>
  )
}
