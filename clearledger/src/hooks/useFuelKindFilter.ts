/**
 * Выбранные виды нефтепродуктов из общего фильтра рабочей области.
 *
 * Один хук на все экраны «Топлива»: вид топлива задаётся в шапке рядом с периодом
 * и областью учёта, и каждый экран обязан читать его оттуда, а не заводить свой
 * селектор. Иначе «Обзор», «Тарифы» и «Маржа» ответят на один вопрос по-разному —
 * а это ровно те цифры, по которым ставят цену.
 *
 * `key` кладётся в queryKey: без него react-query отдаст ответ по прошлому выбору.
 */
import { useMemo } from 'react'
import { useFilters } from '@/contexts/FilterContext'

export function useFuelKindFilter(): { fuelCodes?: number[]; key: string } {
  const { fuelCodes } = useFilters()
  return useMemo(() => {
    const codes = fuelCodes.map(Number).filter(Number.isFinite)
    return { fuelCodes: codes.length ? codes : undefined, key: codes.join(',') }
  }, [fuelCodes])
}
