'use client'

import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Course, Section } from '@/types'

interface Props {
  defaultTerm: string
  onAdd: (courses: Course[]) => void
  onClose: () => void
}

export default function AddCourseModal({ defaultTerm, onAdd, onClose }: Props) {
  const [step, setStep]           = useState<'search' | 'pick'>('search')
  const [courseCode, setCourseCode] = useState('')
  const [term, setTerm]           = useState(defaultTerm)
  const [searching, setSearching] = useState(false)
  const [sections, setSections]   = useState<Section[]>([])
  const [selected, setSelected]   = useState<Set<string>>(new Set())
  const [warnings, setWarnings]   = useState<string[]>([])
  const [adding, setAdding]       = useState(false)
  const [error, setError]         = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function search(e: React.FormEvent) {
    e.preventDefault()
    if (!courseCode.trim() || !term.trim()) {
      setError('Course code and term required.')
      return
    }
    setSearching(true)
    setError('')
    try {
      const res = await api.getSections(term.trim(), courseCode.trim())
      if (res.sections.length === 0) {
        setError(res.warnings[0] ?? 'No sections found.')
        setSearching(false)
        return
      }
      setSections(res.sections)
      setWarnings(res.warnings)
      // Pre-select all
      setSelected(new Set(res.sections.map(s => s.crn)))
      setStep('pick')
    } catch (err: any) {
      setError(err.message ?? 'Search failed.')
    } finally {
      setSearching(false)
    }
  }

  function toggleAll() {
    if (selected.size === sections.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(sections.map(s => s.crn)))
    }
  }

  function toggle(crn: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(crn) ? next.delete(crn) : next.add(crn)
      return next
    })
  }

  async function addSelected() {
    if (selected.size === 0) return
    setAdding(true)
    setError('')
    const toAdd = sections.filter(s => selected.has(s.crn))
    const added: Course[] = []
    const errors: string[] = []

    await Promise.all(
      toAdd.map(async s => {
        try {
          const course = await api.addCourse({
            crn:  s.crn,
            term: term.trim(),
            name: `${s.course_id} §${s.section_id} — ${s.course_name}`,
          })
          added.push(course)
        } catch (err: any) {
          errors.push(`CRN ${s.crn}: ${err.message}`)
        }
      })
    )

    setAdding(false)
    if (added.length > 0) {
      onAdd(added)
      onClose()
    } else {
      setError(errors.join(' · '))
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center p-4 animate-fade-in"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" />

      <div className="relative w-full max-w-md bg-surface rounded-2xl shadow-modal border border-[rgba(99,102,241,0.15)] animate-pop">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-[rgba(99,102,241,0.08)]">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Add Course</h2>
            <p className="text-xs text-slate-600 mt-0.5">
              {step === 'search' ? 'Search by course code' : `${sections.length} sections found — pick which to track`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {step === 'pick' && (
              <button
                onClick={() => { setStep('search'); setError('') }}
                className="text-xs text-slate-500 hover:text-slate-300 transition-colors px-2 py-1 rounded-lg hover:bg-surface-2"
              >
                ← Back
              </button>
            )}
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
        </div>

        {/* Step 1 — Search */}
        {step === 'search' && (
          <form onSubmit={search} className="px-6 py-5 space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1.5">Course Code</label>
              <input
                ref={inputRef}
                value={courseCode}
                onChange={e => setCourseCode(e.target.value.toUpperCase())}
                placeholder="e.g. CS 3510 or CS3510"
                className="input-field font-mono tracking-wide"
                autoComplete="off"
              />
              <p className="text-[11px] text-slate-700 mt-1.5">
                Format: DEPT NNNN — e.g. CS 1332, MATH 1553, ECE 2026
              </p>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1.5">Term</label>
              <input
                value={term}
                onChange={e => setTerm(e.target.value.replace(/\D/g, ''))}
                placeholder="202608"
                className="input-field font-mono"
                maxLength={6}
              />
              <p className="text-[11px] text-slate-700 mt-1.5">
                YYYYSS — 02 Spring · 05 Summer · 08 Fall
              </p>
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/10 border border-red-900/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <div className="flex gap-3 pt-1">
              <button type="button" onClick={onClose} className="btn-ghost flex-1">Cancel</button>
              <button type="submit" disabled={searching} className="btn-primary flex-1">
                {searching ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25"/>
                      <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
                    </svg>
                    Searching…
                  </span>
                ) : 'Search Sections'}
              </button>
            </div>
          </form>
        )}

        {/* Step 2 — Pick sections */}
        {step === 'pick' && (
          <div className="px-6 py-5">
            {warnings.length > 0 && (
              <p className="text-xs text-yellow-600 mb-3">{warnings.join(' · ')}</p>
            )}

            {/* Select all toggle */}
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-slate-500 font-mono">{sections[0]?.course_id} — {term}</span>
              <button
                onClick={toggleAll}
                className="text-xs text-accent hover:text-accent-2 transition-colors"
              >
                {selected.size === sections.length ? 'Deselect all' : 'Select all'}
              </button>
            </div>

            {/* Section list */}
            <div className="space-y-1.5 max-h-64 overflow-y-auto -mx-1 px-1">
              {sections.map(s => {
                const checked = selected.has(s.crn)
                return (
                  <button
                    key={s.crn}
                    onClick={() => toggle(s.crn)}
                    className={`
                      w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left
                      border transition-all duration-150
                      ${checked
                        ? 'bg-accent/10 border-accent/25 text-slate-200'
                        : 'bg-surface-2 border-[rgba(99,102,241,0.08)] text-slate-500 hover:text-slate-300 hover:border-accent/15'
                      }
                    `}
                  >
                    {/* Checkbox */}
                    <span className={`
                      w-4 h-4 rounded-md border flex-shrink-0 flex items-center justify-center transition-colors
                      ${checked ? 'bg-accent border-accent' : 'border-slate-700'}
                    `}>
                      {checked && (
                        <svg width="9" height="9" viewBox="0 0 9 9" fill="none">
                          <path d="M1.5 4.5l2 2 4-4" stroke="white" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </span>

                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium">Section {s.section_id}</span>
                    </div>
                    <span className="text-xs font-mono text-slate-600 flex-shrink-0">CRN {s.crn}</span>
                  </button>
                )
              })}
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/10 border border-red-900/20 rounded-lg px-3 py-2 mt-3">
                {error}
              </p>
            )}

            <div className="flex gap-3 mt-4">
              <button onClick={onClose} className="btn-ghost flex-1">Cancel</button>
              <button
                onClick={addSelected}
                disabled={selected.size === 0 || adding}
                className="btn-primary flex-1"
              >
                {adding ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25"/>
                      <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
                    </svg>
                    Adding…
                  </span>
                ) : `Track ${selected.size} section${selected.size !== 1 ? 's' : ''}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
