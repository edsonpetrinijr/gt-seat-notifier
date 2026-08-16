'use client'

import { useState } from 'react'
import type { Course } from '@/types'
import { getCourseStatus } from '@/types'
import StatusBadge from './StatusBadge'

function relativeTime(iso: string): string {
  if (!iso) return 'pending...'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 5)  return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

interface Props {
  course: Course
  onDelete: (crn: string) => void
}

export default function CourseCard({ course, onDelete }: Props) {
  const [deleting, setDeleting] = useState(false)
  const status = getCourseStatus(course)
  const isOpen = status === 'OPEN'
  const isLoading = status === 'LOADING'

  const shadowCls = isOpen
    ? 'shadow-glow-green hover:shadow-glow-green-hover'
    : 'shadow-card hover:shadow-card-hover'

  const borderCls = isOpen
    ? 'border border-green-500/20'
    : 'border border-[rgba(99,102,241,0.1)]'

  const seatColor =
    status === 'OPEN'     ? 'text-green-400' :
    status === 'WAITLIST' ? 'text-yellow-400' :
    status === 'FULL'     ? 'text-red-400' :
    status === 'ERROR'    ? 'text-red-500' :
    'text-slate-600'

  async function handleDelete() {
    setDeleting(true)
    onDelete(course.crn)
  }

  return (
    <div
      className={`
        relative group bg-surface rounded-2xl p-5 ${borderCls} ${shadowCls}
        transition-all duration-300 hover:-translate-y-0.5 animate-slide-up
        ${isOpen ? 'bg-gradient-to-br from-surface to-[#0a1a10]' : ''}
      `}
    >
      {/* Delete button */}
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
        title="Remove course"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>

      {/* Header */}
      <div className="mb-4">
        <p className="text-xs font-mono text-slate-500 mb-1">
          CRN {course.crn} · {course.term}
        </p>
        <h3 className="text-sm font-semibold text-slate-200 leading-snug pr-6">
          {course.name}
        </h3>
      </div>

      {/* Seat count */}
      <div className="mb-4">
        <div className="flex items-end gap-2 mb-1">
          <span
            key={course.seatsAvailable}
            className={`text-4xl font-bold tabular-nums ${seatColor} ${!isLoading ? 'animate-count-in' : ''}`}
          >
            {isLoading ? '—' : course.seatsAvailable}
          </span>
          <span className="text-slate-600 text-sm mb-1.5">open seats</span>
        </div>

        {!isLoading && course.waitlistAvailable !== null && (
          <p className="text-xs text-slate-600">
            {course.waitlistAvailable > 0
              ? <span className="text-yellow-600">{course.waitlistAvailable} waitlist open</span>
              : 'No waitlist'}
            {course.enrollmentMaximum !== null && (
              <span className="ml-2 text-slate-700">
                · {course.enrollmentActual}/{course.enrollmentMaximum} enrolled
              </span>
            )}
          </p>
        )}

        {course.error && (
          <p className="text-xs text-red-400/70 truncate mt-1" title={course.error}>
            {course.error}
          </p>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between">
        <StatusBadge status={status} />
        <span className="text-[11px] text-slate-700 tabular-nums">
          {relativeTime(course.lastUpdated)}
        </span>
      </div>
    </div>
  )
}
