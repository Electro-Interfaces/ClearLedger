export interface TpViewStep {
  key: string; no: string; label: string; branch: 'main' | 'supply'; date: string | null
  plannedDate: string | null; overdue: boolean; executor?: string | null
}
export interface TpViewBranch {
  key: string; label: string; state: string | null
  stage: { code?: string; name?: string }; performer: { id: string; name: string } | null
  due: string | null; overdue: boolean; startedAt?: string | null; stepEnteredAt?: string | null
  steps: { code: string; name: string; is_initial?: boolean; is_finish?: boolean; visited_at?: string | null }[]
  history: { from_code: string | null; to_code: string | null; at: string }[]
}
export interface TechConnectionView {
  enabled: boolean; scenario: string; branches: TpViewBranch[]; steps: TpViewStep[]
  overdue: boolean; deadlines: { key: string; label: string; due: string; branch: string }[]
  openRemarks: number; stagesTotal: number; stagesAccepted: number; archived: boolean
  syncedAt: string | null; error: string | null
  nextWork: { text: string; due: string | null; performer: { name: string } | null; source: string } | null
  kit?: { required: number; present: number; checked: number; ready: boolean; missing: string[] }
  handover?: { exists: boolean; docId?: string; done: boolean; createdAt?: string
    recipients: { id: string; name: string; status: string; readAt: string | null }[] }
  supplyComplete?: boolean
  stages?: { id: string; title: string; due: string | null; done: string | null; notified: string | null; accepted: string | null; executor: string | null }[]
  remarks?: { id: string; branch: string; text: string; received: string; deadline: string; resolved: string | null; overdue: boolean }[]
}
