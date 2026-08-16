export default function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className="bg-surface rounded-2xl p-5 border border-[rgba(99,102,241,0.08)] shadow-card"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <div className="mb-4">
            <div className="h-3 w-24 bg-surface-3 rounded-md mb-2 animate-pulse" />
            <div className="h-4 w-3/4 bg-surface-3 rounded-md animate-pulse" />
          </div>
          <div className="mb-4">
            <div className="h-10 w-16 bg-surface-3 rounded-lg mb-2 animate-pulse" />
            <div className="h-3 w-32 bg-surface-3 rounded-md animate-pulse" />
          </div>
          <div className="flex items-center justify-between">
            <div className="h-6 w-20 bg-surface-3 rounded-lg animate-pulse" />
            <div className="h-3 w-14 bg-surface-3 rounded-md animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  )
}
