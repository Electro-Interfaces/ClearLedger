/**
 * Пересчёт размера карты, когда её контейнер изменился.
 *
 * Leaflet считает размеры один раз при создании и сам за контейнером не следит: при
 * развороте панели на весь экран карта остаётся прежнего размера, а окно вокруг неё
 * становится больше — получается полотно, обрезанное справа и снизу, с пустотой по
 * краям (замечание МАГа 13.09.2026).
 *
 * `ResizeObserver` ловит любое изменение — разворот, сворачивание рельсы, смену
 * ширины окна, — а не только тот случай, ради которого это писалось.
 */
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'

export function MapResize({ trigger }: { trigger?: unknown }) {
  const map = useMap()

  useEffect(() => {
    // Пересчёт после отрисовки: на момент смены флага контейнер ещё старого размера.
    const t = setTimeout(() => map.invalidateSize(), 0)
    return () => clearTimeout(t)
  }, [map, trigger])

  useEffect(() => {
    const el = map.getContainer()
    const obs = new ResizeObserver(() => map.invalidateSize())
    obs.observe(el)
    return () => obs.disconnect()
  }, [map])

  return null
}
