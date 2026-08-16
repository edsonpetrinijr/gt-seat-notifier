import type { CourseStatus } from '@/types'

const configs: Record<CourseStatus, { label: string; cls: string; dot: string }> = {
  OPEN:    { label: 'OPEN',    cls: 'bg-green-500/10 text-green-400 border border-green-500/20',  dot: 'bg-green-400' },
  WAITLIST:{ label: 'WAITLIST',cls: 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20', dot: 'bg-yellow-400' },
  FULL:    { label: 'FULL',    cls: 'bg-red-500/10 text-red-400 border border-red-500/20',        dot: 'bg-red-500' },
  LOADING: { label: '...',     cls: 'bg-slate-800/50 text-slate-500 border border-slate-700/30',  dot: 'bg-slate-600' },
  ERROR:   { label: 'ERROR',   cls: 'bg-red-900/20 text-red-400 border border-red-900/30',        dot: 'bg-red-500' },
}

export default function StatusBadge({ status }: { status: CourseStatus }) {
  const { label, cls, dot } = configs[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold tracking-widest ${cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot} ${status === 'OPEN' ? 'animate-pulse-dot' : ''}`} />
      {label}
    </span>
  )
}
