import { Link } from 'react-router-dom'
import { Fuel, Settings, ArrowRight, ClipboardList, Truck } from 'lucide-react'

export function OnboardingScreen() {
  return (
    <div className="flex items-center justify-center min-h-[70vh]">
      <div className="relative max-w-lg w-full mx-4">
        <div className="absolute -inset-4 bg-primary/5 rounded-3xl blur-2xl" />
        <div className="relative bg-card border border-border rounded-2xl p-8 md:p-12 text-center space-y-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 mx-auto">
            <Fuel className="h-8 w-8 text-primary" />
          </div>
          <div className="space-y-2">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight">GIG Fuel Ledger</h1>
            <p className="text-muted-foreground leading-relaxed">
              Автоматизация учёта нефтепродуктов<br />на сети АЗС ГазИнвестГрупп
            </p>
          </div>
          <div className="pt-2">
            <Link
              to="/settings"
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <Settings className="h-4 w-4" />
              Настроить подключение
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="pt-4 flex items-center justify-center gap-6 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <ClipboardList className="h-3.5 w-3.5" /> Сменные отчёты
            </span>
            <span className="flex items-center gap-1.5">
              <Truck className="h-3.5 w-3.5" /> Поступления ТТН
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
