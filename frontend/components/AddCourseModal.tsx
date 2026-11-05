'use client'

import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Course, Season } from '@/types'

interface Props {
  defaultSeason: Season
  onAdd: (course: Course) => void
  onClose: () => void
}

const SEASONS: Array<{ value: Season; label: string }> = [
  { value: 'spring', label: 'Spring' },
  { value: 'summer', label: 'Summer' },
  { value: 'fall',   label: 'Fall' },
]

export default function AddCourseModal({ defaultSeason, onAdd, onClose }: Props) {
  const [courseId, setCourseId] = useState('')
  const [season, setSeason]     = useState<Season>(defaultSeason)
  const [adding, setAdding]     = useState(false)
  const [error, setError]       = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!courseId.trim()) {
      setError('Course code required.')
      return
    }
    setAdding(true)
    setError('')
    try {
      const course = await api.addCourse({ courseId: courseId.trim(), season })
      onAdd(course)
      onClose()
    } catch (err: any) {
      setError(err.message ?? 'Failed to add course.')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center p-4 animate-fade-in"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" />

      <div className="relative w-full max-w-md bg-surface rounded-2xl shadow-modal border border-[rgba(99,102,241,0.15)] animate-pop">
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-[rgba(99,102,241,0.08)]">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Track Course</h2>
            <p className="text-xs text-slate-600 mt-0.5">Every section is tracked automatically</p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg bg-surface-2 hover:bg-surface-3 text-slate-500 hover:text-slate-300
                       flex items-center justify-center transition-colors border border-[rgba(99,102,241,0.1)]"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Course Code</label>
            <input
              ref={inputRef}
              value={courseId}
              onChange={e => setCourseId(e.target.value.toUpperCase())}
              placeholder="e.g. CS 3510 or CS3510"
              className="input-field font-mono tracking-wide"
              autoComplete="off"
            />
            <p className="text-[11px] text-slate-700 mt-1.5">
              Format: DEPT NNNN — e.g. CS 1332, MATH 1553
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Term</label>
            <div className="flex gap-2">
              {SEASONS.map(s => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => setSeason(s.value)}
                  className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-colors ${
                    season === s.value
                      ? 'bg-accent/15 border-accent/40 text-slate-100'
                      : 'bg-surface-2 border-[rgba(99,102,241,0.08)] text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <p className="text-xs text-red-400 bg-red-900/10 border border-red-900/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-ghost flex-1">Cancel</button>
            <button type="submit" disabled={adding} className="btn-primary flex-1">
              {adding ? 'Adding…' : 'Track Course'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
