/**
 * Фасад для работы с категориями.
 * Категории теперь определяются профилем компании (profiles.ts).
 * Этот модуль предоставляет удобные функции для получения
 * категорий/подкатегорий/типов документов по profileId.
 */

import { getProfile, type ProfileId, type Category, type SubCategory, type DocumentType, type MetadataField } from './profiles'

// Re-export типов для обратной совместимости
export type { Category, SubCategory, DocumentType, MetadataField }

/** Получить все категории для профиля */
export function getCategoriesForProfile(profileId: ProfileId): Category[] {
  return getProfile(profileId).categories
}

/** Найти категорию по id внутри профиля */
export function getCategoryById(profileId: ProfileId, categoryId: string): Category | undefined {
  return getProfile(profileId).categories.find((c) => c.id === categoryId)
}

/** Получить подкатегории для категории в профиле */
export function getSubcategories(profileId: ProfileId, categoryId: string): SubCategory[] {
  return getCategoryById(profileId, categoryId)?.subcategories ?? []
}

/** Найти подкатегорию */
export function getSubcategoryById(profileId: ProfileId, categoryId: string, subId: string): SubCategory | undefined {
  return getSubcategories(profileId, categoryId).find((s) => s.id === subId)
}

/** Получить типы документов для подкатегории */
export function getDocumentTypes(profileId: ProfileId, categoryId: string, subId: string): DocumentType[] {
  return getSubcategoryById(profileId, categoryId, subId)?.documentTypes ?? []
}

/** Найти тип документа по id (поиск по всему профилю) */
export function getDocumentTypeById(profileId: ProfileId, docTypeId: string): DocumentType | undefined {
  const profile = getProfile(profileId)
  for (const cat of profile.categories) {
    for (const sub of cat.subcategories) {
      const dt = sub.documentTypes.find((d) => d.id === docTypeId)
      if (dt) return dt
    }
  }
  return undefined
}

/** Получить метаполя для типа документа */
export function getMetadataFields(profileId: ProfileId, docTypeId: string): MetadataField[] {
  return getDocumentTypeById(profileId, docTypeId)?.metadataFields ?? []
}

/** Получить все типы документов с OCR для профиля (плоский список) */
export function getOcrDocumentTypes(profileId: ProfileId): DocumentType[] {
  const result: DocumentType[] = []
  const profile = getProfile(profileId)
  for (const cat of profile.categories) {
    for (const sub of cat.subcategories) {
      for (const dt of sub.documentTypes) {
        if (dt.ocrEnabled) result.push(dt)
      }
    }
  }
  return result
}

/** Получить шаблоны коннекторов для профиля */
export function getConnectorTemplates(profileId: ProfileId) {
  return getProfile(profileId).connectorTemplates
}

/** Плоский список всех типов документов профиля */
export function getAllDocumentTypes(profileId: ProfileId): Array<DocumentType & { categoryId: string; subcategoryId: string }> {
  const result: Array<DocumentType & { categoryId: string; subcategoryId: string }> = []
  const profile = getProfile(profileId)
  for (const cat of profile.categories) {
    for (const sub of cat.subcategories) {
      for (const dt of sub.documentTypes) {
        result.push({ ...dt, categoryId: cat.id, subcategoryId: sub.id })
      }
    }
  }
  return result
}
