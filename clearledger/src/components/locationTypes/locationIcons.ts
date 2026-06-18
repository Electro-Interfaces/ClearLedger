/** Реестр иконок типов точек (по имени lucide) + резолвер с фолбэком. */
import type { ComponentType } from 'react'
import { Fuel, Zap, Store, Building2, Warehouse, MapPin, Utensils, Flame } from 'lucide-react'

export const LOCATION_ICON_REGISTRY: Record<string, ComponentType<{ className?: string }>> = {
  Fuel, Zap, Store, Building2, Warehouse, MapPin, Utensils, Flame,
}

export const LOCATION_ICON_NAMES = Object.keys(LOCATION_ICON_REGISTRY)

export function resolveLocationIcon(name?: string): ComponentType<{ className?: string }> {
  return (name && LOCATION_ICON_REGISTRY[name]) || MapPin
}
