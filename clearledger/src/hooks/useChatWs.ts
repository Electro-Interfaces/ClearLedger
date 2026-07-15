/**
 * WebSocket-клиент чата: /api/chat/ws?token=JWT.
 * Подписка на каналы chat:{roomId}, typing, обработка live-событий, авто-реконнект.
 */
import { useEffect, useRef, useCallback } from 'react'
import { getToken } from '@/services/apiClient'

export interface WsEvent {
  type: string
  channel?: string
  [k: string]: unknown
}

function wsUrl(): string | null {
  const base = import.meta.env.VITE_API_URL ?? ''
  const token = getToken()
  if (!base || !token) return null
  // http(s)://host → ws(s)://host
  const proto = base.startsWith('https') ? 'wss' : 'ws'
  const host = base.replace(/^https?:\/\//, '').replace(/\/$/, '')
  return `${proto}://${host}/api/chat/ws?token=${encodeURIComponent(token)}`
}

/**
 * @param channels — каналы для подписки (напр. [`chat:${roomId}`]); меняются при смене комнаты.
 * @param onEvent — обработчик входящих WS-событий.
 */
export function useChatWs(channels: string[], onEvent: (e: WsEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const subsRef = useRef<Set<string>>(new Set())
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent
  const channelsRef = useRef<string[]>(channels)
  channelsRef.current = channels
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const aliveRef = useRef(true)

  const subscribe = useCallback((ch: string) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN && !subsRef.current.has(ch)) {
      ws.send(JSON.stringify({ type: 'subscribe', channel: ch }))
      subsRef.current.add(ch)
    }
  }, [])

  const sendTyping = useCallback((ch: string) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'typing', channel: ch }))
  }, [])

  const connect = useCallback(() => {
    const url = wsUrl()
    if (!url) return
    const ws = new WebSocket(url)
    wsRef.current = ws
    ws.onopen = () => {
      subsRef.current.clear()
      channelsRef.current.forEach(subscribe)
    }
    ws.onmessage = (ev) => {
      try {
        onEventRef.current(JSON.parse(ev.data))
      } catch { /* невалидный кадр */ }
    }
    ws.onclose = () => {
      wsRef.current = null
      subsRef.current.clear()
      if (aliveRef.current) reconnectRef.current = setTimeout(connect, 3000)
    }
    ws.onerror = () => ws.close()
  }, [subscribe])

  useEffect(() => {
    aliveRef.current = true
    connect()
    return () => {
      aliveRef.current = false
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  // подписка на актуальный набор каналов при их смене
  useEffect(() => {
    channels.forEach(subscribe)
  }, [channels, subscribe])

  return { subscribe, sendTyping }
}
