import {
  Mail, Database, Globe, Server, Zap, Upload, MessageCircle, FileCode,
  type LucideIcon,
} from 'lucide-react'

const iconMap: Record<string, LucideIcon> = {
  email: Mail,
  '1c': Database,
  oneC: Database,
  rest: Globe,
  api: Globe,
  ftp: Server,
  webhook: Zap,
  upload: Upload,
  manual: Upload,
  whatsapp: MessageCircle,
  telegram: MessageCircle,
  edi: FileCode,
}

interface Props {
  type: string
  className?: string
}

export function ChannelTypeIcon({ type, className = 'size-5' }: Props) {
  const Icon = iconMap[type] ?? Globe
  return <Icon className={className} />
}
