interface Props {
  onAdd: () => void
}

export default function EmptyState({ onAdd }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-surface border border-[rgba(99,102,241,0.12)] flex items-center justify-center mb-5 shadow-card">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" className="text-slate-600">
          <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          <path d="M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v0a2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2v0Z" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M12 12v4M10 14h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </div>
      <h2 className="text-lg font-semibold text-slate-300 mb-2">No courses tracked</h2>
      <p className="text-sm text-slate-600 mb-6 max-w-xs">
        Add a course by CRN to start monitoring seat availability and get notified when spots open.
      </p>
      <button onClick={onAdd} className="btn-primary">
        Add your first course
      </button>
    </div>
  )
}
