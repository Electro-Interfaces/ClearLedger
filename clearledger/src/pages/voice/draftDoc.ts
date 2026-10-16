/**
 * Документ настроек как данные: разница двух версий по путям, чтение и запись поля
 * по пути, короткий показ значения для подписи «было …».
 */

// ——— Разница документов ———

const канон = (v: unknown) => JSON.stringify(v, (_k, x) =>
  x && typeof x === 'object' && !Array.isArray(x)
    ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x)

const объект = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x)

export interface Изменение { path: string; op?: 'add' | 'remove' | 'replace'; from?: unknown; to?: unknown }

/** Разница по путям (JSON Pointer) — та же, что у узла (config.ts `diff`): массивы целиком. */
export function разница(a: unknown, b: unknown, path = ''): Изменение[] {
  if (объект(a) && объект(b)) {
    return [...new Set([...Object.keys(a), ...Object.keys(b)])].sort().flatMap(k => {
      const p = `${path}/${k.replaceAll('~', '~0').replaceAll('/', '~1')}`
      if (!(k in a)) return [{ path: p, op: 'add' as const, to: b[k] }]
      if (!(k in b)) return [{ path: p, op: 'remove' as const, from: a[k] }]
      return разница(a[k], b[k], p)
    })
  }
  return канон(a) === канон(b) ? [] : [{ path, op: 'replace', from: a, to: b }]
}

/** Значение по JSON Pointer; нет — undefined. */
export function поУказателю(doc: unknown, path: string): unknown {
  let x: unknown = doc
  for (const part of path.split('/').slice(1)) {
    const k = part.replaceAll('~1', '/').replaceAll('~0', '~')
    if (Array.isArray(x)) x = x[Number(k)]
    else if (объект(x)) x = x[k]
    else return undefined
  }
  return x
}

/** Записать значение по пути из ключей, не трогая исходник; undefined — убрать поле (сработает значение по умолчанию). */
export function записать<B>(doc: B, ключи: string[], значение: unknown): B {
  const [k, ...rest] = ключи
  const src = (объект(doc) ? doc : {}) as Record<string, unknown>
  const next = { ...src }
  if (!rest.length) {
    if (значение === undefined) delete next[k]
    else next[k] = значение
  } else {
    next[k] = записать(src[k], rest, значение)
  }
  return next as B
}

/** Значение для подписи «было …»: коротко и словами. */
export function показать(v: unknown): string {
  if (v === undefined || v === null || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (Array.isArray(v)) return v.length ? v.map(x => (typeof x === 'object' ? канон(x) : String(x))).join(', ') : 'пусто'
  if (typeof v === 'object') return канон(v)
  return String(v)
}
