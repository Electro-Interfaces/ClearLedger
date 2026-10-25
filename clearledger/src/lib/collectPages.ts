/** Полная выгрузка: не выдаём обрыв, дубли или изменившийся набор за полный файл. */
export async function collectPages<T extends { id: string }>(
  fetchPage: (offset: number, limit: number) => Promise<{ rows: T[]; total: number }>,
  size = 1000,
): Promise<T[]> {
  const result: T[] = [], seen = new Set<string>()
  let expected: number | undefined
  do {
    const page = await fetchPage(result.length, size)
    expected ??= page.total
    if (page.total !== expected || expected > 100000 || expected < 0) {
      throw new Error('Набор изменился или превышает лимит выгрузки. Повторите с более узким отбором.')
    }
    for (const row of page.rows) {
      if (seen.has(row.id)) throw new Error('Повтор записи при выгрузке. Повторите после обновления данных.')
      seen.add(row.id); result.push(row)
    }
    if (result.length > expected || (!page.rows.length && result.length < expected)) {
      throw new Error('Получена неполная выгрузка. Повторите попытку.')
    }
  } while (result.length < expected)
  return result
}
