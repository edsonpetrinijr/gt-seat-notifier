'use client'

import { useState } from 'react'
import type { Course, CourseStatus } from '@/types'
import { courseStatus } from '@/types'
import StatusBadge from './StatusBadge'

function relativeTime(iso: string): string {
  if (!iso) return 'pending...'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 5)  return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

const SEAT_COLOR: Record<CourseStatus, string> = {
  OPEN: 'text-green-400',
  WAITLIST: 'text-yellow-400',
  FULL: 'text-red-400',
  ERROR: 'text-red-500',
  LOADING: 'text-slate-600',
}

interface Props {
  course: Course
  onDelete: (courseId: string) => void
}

export default function CourseCard({ course, onDelete }: Props) {
  const [deleting, setDeleting] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const status = courseStatus(course)
  const isOpen = status === 'OPEN'
  const rec = course.recommended
  const best = rec?.lecture ?? null
  const bestSeats = rec ? Math.min(rec.lecture.seatsAvailable ?? Infinity, rec.lab?.seatsAvailable ?? Infinity) : null
  const bestWaitlist = rec ? Math.min(rec.lecture.waitlistAvailable ?? Infinity, rec.lab?.waitlistAvailable ?? Infinity) : null
  const rest = course.sections.filter(s => s.crn !== rec?.lecture.crn && s.crn !== rec?.lab?.crn)

  const shadowCls = isOpen
    ? 'shadow-glow-green hover:shadow-glow-green-hover'
    : 'shadow-card hover:shadow-card-hover'
  const borderCls = isOpen
    ? 'border border-green-500/20'
    : 'border border-[rgba(99,102,241,0.1)]'

  async function handleDelete() {
    setDeleting(true)
    onDelete(course.courseId)
  }

  return (
    <div
      className={`
        relative group bg-surface rounded-2xl p-5 ${borderCls} ${shadowCls}
        transition-all duration-300 hover:-translate-y-0.5 animate-slide-up
        ${isOpen ? 'bg-gradient-to-br from-surface to-[#0a1a10]' : ''}
      `}
    >
      <button
        onClick={handleDelete}
        disabled={deleting}
        className="
          absolute top-4 right-4 opacity-0 group-hover:opacity-100
          w-7 h-7 rounded-lg bg-surface-2 hover:bg-red-900/40
          text-slate-600 hover:text-red-400
          flex items-center justify-center transition-all duration-150
          border border-[rgba(99,102,241,0.1)] hover:border-red-500/20
          disabled:opacity-40
        "
        title="Stop tracking course"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>

      <div className="mb-4">
        <p className="text-xs font-mono text-slate-500 mb-1">
          {course.term} · {course.sections.length} section{course.sections.length !== 1 ? 's' : ''}
        </p>
        <h3 className="text-sm font-semibold text-slate-200 leading-snug pr-6">
          {course.courseId} — {course.courseName}
        </h3>
      </div>

      {/* Best pick */}
      <div className="mb-3">
        {rec && best ? (
          <>
            <div className="flex items-end gap-2 mb-1">
              <span className={`text-4xl font-bold tabular-nums ${SEAT_COLOR[rec.status]} animate-count-in`}>
                {rec.status === 'OPEN' ? bestSeats : bestWaitlist}
              </span>
              <span className="text-slate-600 text-sm mb-1.5">
                {rec.status === 'OPEN' ? 'open seats' : 'waitlist spots'} · best pick §{best.sectionId}
                {rec.lab ? ` + lab §${rec.lab.sectionId}` : ''}
              </span>
            </div>
            <p className="text-xs text-slate-600">
              CRN {best.crn}{rec.lab ? ` / ${rec.lab.crn}` : ''} · {best.enrollmentActual}/{best.enrollmentMaximum} enrolled
            </p>
            {course.scheduleConflict ? (
              <p className="text-[11px] text-amber-400 mt-1">
                ⚠ conflicts with another tracked course — can't fit both
              </p>
            ) : rec.timePenalty === 0 ? (
              <p className="text-[11px] text-slate-600 mt-1">✓ fits your hours</p>
            ) : (
              <p className="text-[11px] text-amber-500/80 mt-1">
                ⚠ outside preferred hours (before 9:30, lunch, or after 6pm)
              </p>
            )}
          </>
        ) : (
          <div className="flex items-end gap-2 mb-1">
            <span className="text-4xl font-bold tabular-nums text-slate-600">
              {course.sections.length === 0 || course.sections.every(s => s.status === 'LOADING') ? '—' : '0'}
            </span>
            <span className="text-slate-600 text-sm mb-1.5">all sections full</span>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between mb-1">
        <StatusBadge status={status} />
        <span className="text-[11px] text-slate-700 tabular-nums">
          {relativeTime(best?.lastUpdated ?? course.sections[0]?.lastUpdated ?? '')}
        </span>
      </div>

      {rest.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-[11px] text-accent hover:text-accent-2 transition-colors mt-2"
          >
            {expanded ? 'Hide' : 'Show'} {rest.length} other section{rest.length !== 1 ? 's' : ''}
          </button>
          {expanded && (
            <div className="mt-2 space-y-1 border-t border-[rgba(99,102,241,0.08)] pt-2">
              {rest.map(s => (
                <div key={s.crn} className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-500 font-mono">§{s.sectionId} · CRN {s.crn}</span>
                  <span className={SEAT_COLOR[s.status]}>
                    {s.status === 'OPEN' ? `${s.seatsAvailable} open` :
                     s.status === 'WAITLIST' ? `${s.waitlistAvailable} WL` :
                     s.status === 'LOADING' ? 'loading…' : 'full'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
