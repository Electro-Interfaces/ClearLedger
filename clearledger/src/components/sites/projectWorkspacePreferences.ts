export const PROJECT_COLUMNS = [
  ['kind', 'Вид работ'], ['placeKind', 'Тип объекта'], ['phase', 'Этап проекта'],
  ['stage', 'Стадия'], ['owner', 'Ответственный'], ['nextAction', 'Следующий шаг'], ['due', 'Срок'],
] as const

export const PROJECT_WORKSPACE_DEFAULTS = {
  kind: '', placeKind: '', columns: PROJECT_COLUMNS.map(([key]) => key as string),
}
export type ProjectWorkspacePreferences = typeof PROJECT_WORKSPACE_DEFAULTS
