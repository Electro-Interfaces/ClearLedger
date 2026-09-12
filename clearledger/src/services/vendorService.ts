import { get, post } from './apiClient'

export interface VendorProduct {
  code: string
  name: string
  title: string
  description: string
  category: string
  stage: 'available' | 'announced'
  image: string | null
  appCodes: string[]
  demo: { code: string; title: string; description: string; ready: boolean; allowed: boolean } | null
}

export interface VendorCatalog {
  products: VendorProduct[]
  help: { question: string; answer: string }[]
}

export interface VendorDocument {
  id: string
  name: string
  size: number
  createdAt: string | null
  author: string
  topicCode: string | null
  topicTitle: string | null
}

const vendorPath = (code: string) => `/api/vendor/${encodeURIComponent(code)}`

export const getVendorCatalog = (code: string, companyId: string) =>
  get<VendorCatalog>(`${vendorPath(code)}/catalog`, { company_id: companyId })

export const getVendorDocuments = (code: string, companyId: string) =>
  get<{ items: VendorDocument[] }>(`${vendorPath(code)}/documents`, { company_id: companyId })

export const launchVendorDemo = (code: string, companyId: string, demoId: string) =>
  post<{ url: string; expires_in: number }>(
    `${vendorPath(code)}/demo?company_id=${encodeURIComponent(companyId)}`, { demo_id: demoId })
