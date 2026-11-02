import { listDocs, type DocFilters } from '../../src/services/docsService'

// Компилятор проверяет тот же путь, что ContractDocumentsBlock; вызовы не исполняются.
const filters: DocFilters = { ref: 'contract:opaque/id' }
void (() => listDocs('opaque-company', filters))
void (() => listDocs('opaque-company', { ref: 'contract:opaque/id' }))
// @ts-expect-error Backend ref — строка, не числовой идентификатор.
const invalid: DocFilters = { ref: 42 }
void invalid
