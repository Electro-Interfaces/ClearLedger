/** Only the unrelated support dock context is excluded from the passport fixture. */
export function useSupportContext() {
  return { openInteraction: () => { throw new Error('Support actions are outside passport preservation QA') } }
}
