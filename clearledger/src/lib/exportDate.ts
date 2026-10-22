/** День выгрузки в часовом поясе пользователя, без сдвига к дате UTC. */
export function exportDateStamp(date = new Date(), timeZone?: string): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone }).format(date)
}
