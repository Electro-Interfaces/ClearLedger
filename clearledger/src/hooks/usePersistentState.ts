/**
 * useState с персистом значения в localStorage — «липкость» из стандарта
 * управления сложностью (§2, правило 4): выбор пользователя (активная вкладка,
 * раскрытый раздел, режим вида) переживает перезагрузку и навигацию, чтобы
 * ежедневный эксперт не восстанавливал состояние каждый заход.
 *
 * Ключ должен быть стабилен в рамках жизни компонента. При смене ключа значение
 * НЕ перечитывается автоматически — либо ключ стабилен, либо перемонтируйте
 * компонент через React key.
 */
import { useEffect, useState } from 'react'

export function usePersistentState<T>(
  key: string,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [state, setState] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw !== null ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state))
    } catch {
      /* ignore quota */
    }
  }, [key, state])

  return [state, setState]
}
