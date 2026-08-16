export type PwaInstallPrompt = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

type InstallState = {
  installed: boolean
  promptAvailable: boolean
}

let initialized = false
let pendingPrompt: PwaInstallPrompt | null = null
let installed = false
const listeners = new Set<(state: InstallState) => void>()

export function isPwaInstalled(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true
}

function state(): InstallState {
  return {
    installed: installed || isPwaInstalled(),
    promptAvailable: pendingPrompt !== null,
  }
}

function notify(): void {
  const next = state()
  listeners.forEach((listener) => listener(next))
}

export function initPwaInstall(): void {
  if (initialized) return
  initialized = true
  installed = isPwaInstalled()

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    pendingPrompt = event as PwaInstallPrompt
    notify()
  })

  window.addEventListener('appinstalled', () => {
    installed = true
    pendingPrompt = null
    notify()
  })
}

export function subscribePwaInstall(listener: (state: InstallState) => void): () => void {
  listeners.add(listener)
  listener(state())
  return () => { listeners.delete(listener) }
}

export function hasPwaInstallPrompt(): boolean {
  return pendingPrompt !== null
}

export async function requestPwaInstall(): Promise<'accepted' | 'dismissed' | null> {
  const prompt = pendingPrompt
  if (!prompt) return null
  try {
    await prompt.prompt()
    const choice = await prompt.userChoice
    return choice.outcome
  } finally {
    pendingPrompt = null
    notify()
  }
}
