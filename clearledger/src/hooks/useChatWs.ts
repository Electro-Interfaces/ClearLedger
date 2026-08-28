/**
 * WebSocket-клиент чата: /api/chat/ws?token=JWT.
 * Подписка на каналы chat:{roomId}, typing, обработка live-событий, авто-реконнект.
 */
import { useEffect, useRef, useCallback, useState } from 'react'
import { getToken, isDemoMode } from '@/services/apiClient'

export interface WsEvent {
  type: string
  channel?: string
  [k: string]: unknown
}

function wsUrl(): string | null {
  if (isDemoMode()) return null
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
 * @param onReconnect — связь восстановилась после обрыва. Пока её не было, сообщения
 *   приходить перестали, а лента об этом не знала: человек час смотрел на «тихий» чат,
 *   считая, что ему не пишут. Обработчик перезапрашивает то, что пропущено.
 */
export function useChatWs(
  channels: string[],
  onEvent: (e: WsEvent) => void,
  onReconnect?: () => void,
) {
  const wsRef = useRef<WebSocket | null>(null)
  const subsRef = useRef<Set<string>>(new Set())
  const onEventRef = useRef(onEvent)
  const channelsRef = useRef<string[]>(channels)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onReconnectRef = useRef(onReconnect)
  const wasOpenRef = useRef(false)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    onEventRef.current = onEvent
    channelsRef.current = channels
    onReconnectRef.current = onReconnect
  }, [channels, onEvent, onReconnect])

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

  useEffect(() => {
    let disposed = false
    let lastFrameAt = Date.now()
    const connect = () => {
      const url = wsUrl()
      if (!url || disposed) return
      const ws = new WebSocket(url)
      wsRef.current = ws
      ws.onopen = () => {
        lastFrameAt = Date.now()
        subsRef.current.clear()
        channelsRef.current.forEach(subscribe)
        setConnected(true)
        if (wasOpenRef.current) onReconnectRef.current?.()
        wasOpenRef.current = true
      }
      ws.onmessage = (ev) => {
        lastFrameAt = Date.now()
        try {
          const event = JSON.parse(ev.data)
          if (event.type !== 'pong') onEventRef.current(event)
        } catch { /* невалидный кадр */ }
      }
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        subsRef.current.clear()
        setConnected(false)
        if (!disposed) reconnectRef.current = setTimeout(connect, 3000)
      }
      ws.onerror = () => ws.close()
    }
    connect()
    const heartbeat = setInterval(() => {
      const ws = wsRef.current
      if (ws?.readyState !== WebSocket.OPEN) return
      if (Date.now() - lastFrameAt > 70000) ws.close()
      else ws.send(JSON.stringify({ type: 'ping' }))
    }, 25000)
    return () => {
      disposed = true
      clearInterval(heartbeat)
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [subscribe])

  // подписка на актуальный набор каналов при их смене
  useEffect(() => {
    channels.forEach(subscribe)
  }, [channels, subscribe])

  return { subscribe, sendTyping, connected }
}
