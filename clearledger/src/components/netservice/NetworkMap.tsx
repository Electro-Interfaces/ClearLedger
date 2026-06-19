/**
 * Карта станций сети — географический разброс заявок (MVP на recharts ScatterChart,
 * без тайловой подложки; leaflet — следующая фаза). Координаты из network-health.
 */
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { NetPoint } from '@/services/netServiceService'

export function NetworkMap({ points }: { points: NetPoint[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Карта открытых заявок · {points.length}</CardTitle>
      </CardHeader>
      <CardContent>
        {points.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Нет координат для отображения.</p>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <XAxis type="number" dataKey="lng" name="Долгота" domain={['dataMin', 'dataMax']}
                tick={{ fontSize: 10 }} tickFormatter={(v) => Number(v).toFixed(1)} />
              <YAxis type="number" dataKey="lat" name="Широта" domain={['dataMin', 'dataMax']}
                tick={{ fontSize: 10 }} tickFormatter={(v) => Number(v).toFixed(1)} />
              <ZAxis range={[36, 36]} />
              <Tooltip
                cursor={{ strokeDasharray: '3 3' }}
                contentStyle={{ backgroundColor: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                formatter={(_v, _n, props: { payload?: NetPoint }) => {
                  const p = props?.payload
                  return p ? [`${p.name ?? p.number} · ${p.status ?? ''}`, `#${p.number}`] : ['', '']
                }}
              />
              <Scatter data={points} fillOpacity={0.8}>
                {points.map((p) => (
                  <Cell key={p.id} fill={p.color ? `#${p.color}` : 'hsl(var(--primary))'} />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
