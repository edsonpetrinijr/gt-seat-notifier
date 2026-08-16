'use client'

interface Props {
  courseCount: number
  openCount: number
  onAddCourse: () => void
  onSettings: () => void
}

export default function Navbar({ courseCount, openCount, onAddCourse, onSettings }: Props) {
  return (
    <header className="sticky top-0 z-30 glass border-b border-[rgba(99,102,241,0.08)]">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="5.5" stroke="#818cf8" strokeWidth="1.2"/>
              <path d="M7 4v3l2 1.5" stroke="#818cf8" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="text-sm font-semibold text-slate-200 hidden sm:block">GT Seat Notifier</span>

          {courseCount > 0 && (
            <div className="flex items-center gap-1.5 ml-1">
              <span className="text-xs text-slate-700">·</span>
              <span className="text-xs text-slate-500">{courseCount} tracked</span>
              {openCount > 0 && (
                <>
                  <span className="text-xs text-slate-700">·</span>
                  <span className="text-xs text-green-500 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse-dot" />
                    {openCount} open
                  </span>
                </>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={onSettings}
            className="w-8 h-8 rounded-lg bg-surface hover:bg-surface-2 text-slate-500 hover:text-slate-300
                       flex items-center justify-center transition-colors
                       border border-[rgba(99,102,241,0.1)] hover:border-accent/20"
            title="Settings"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="2" stroke="currentColor" strokeWidth="1.2"/>
              <path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.5 2.5l1 1M10.5 10.5l1 1M11.5 2.5l-1 1M3.5 10.5l-1 1"
                stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            </svg>
          </button>

          <button onClick={onAddCourse} className="btn-primary flex items-center gap-2 !py-2 !px-3">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            <span className="hidden sm:inline">Add Course</span>
          </button>
        </div>
      </div>
    </header>
  )
}
