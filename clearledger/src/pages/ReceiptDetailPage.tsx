import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

export function ReceiptDetailPage() {
  return (
    <div className="space-y-4">
      <Link to="/receipts" className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Поступления
      </Link>
      <p className="text-muted-foreground">Детальный просмотр ТТН — в следующей версии.</p>
    </div>
  )
}

export default ReceiptDetailPage
