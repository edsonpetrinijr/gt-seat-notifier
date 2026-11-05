'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Course, Season } from '@/types'
import { courseStatus, seasonFromTerm } from '@/types'
import Navbar from '@/components/Navbar'
import CourseCard from '@/components/CourseCard'
import WeekCalendar from '@/components/WeekCalendar'
import AddCourseModal from '@/components/AddCourseModal'
import SettingsDrawer from '@/components/SettingsDrawer'
import LoadingSkeleton from '@/components/LoadingSkeleton'
import EmptyState from '@/components/EmptyState'
import { ToastProvider, useToast } from '@/components/Toast'

const POLL_INTERVAL = 15_000

function Dashboard() {
  const { toast } = useToast()
  const [courses, setCourses]           = useState<Course[]>([])
  const [loading, setLoading]           = useState(true)
  const [defaultSeason, setDefaultSeason] = useState<Season>('fall')
  const [showModal, setShowModal]       = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [view, setView]                 = useState<'cards' | 'week'>('cards')
  const prevOpenRef = useRef<Record<string, number>>({})

  const fetchCourses = useCallback(async (silent = false) => {
    try {
      const data = await api.getCourses()

      // Detect newly opened seats
      data.forEach(c => {
        const prev = prevOpenRef.current[c.courseId]
        if (prev !== undefined && prev === 0 && c.openCount > 0) {
          toast(`${c.courseId} — seat opened!`, 'success')
        }
        prevOpenRef.current[c.courseId] = c.openCount
      })

      setCourses(data)
      if (!silent) setLoading(false)
    } catch {
      if (!silent) {
        setLoading(false)
        toast('Cannot reach backend. Is it running?', 'error')
      }
    }
  }, [toast])

  useEffect(() => {
    fetchCourses()
    api.getSettings().then(s => setDefaultSeason(seasonFromTerm(s.term))).catch(() => {})

    const id = setInterval(() => fetchCourses(true), POLL_INTERVAL)
    return () => clearInterval(id)
  }, [fetchCourses])

  function handleAdd(course: Course) {
    setCourses(prev => [...prev, course])
    prevOpenRef.current[course.courseId] = course.openCount
    toast(`${course.courseId} added`, 'success')
  }

  async function handleDelete(courseId: string) {
    try {
      await api.deleteCourse(courseId)
      setCourses(prev => prev.filter(c => c.courseId !== courseId))
      delete prevOpenRef.current[courseId]
      toast(`${courseId} removed`, 'info')
    } catch {
      toast('Failed to remove course', 'error')
    }
  }

  const openCount = courses.filter(c => courseStatus(c) === 'OPEN').length

  return (
    <div className="min-h-screen bg-bg">
      {/* Ambient background gradient */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse 80% 50% at 50% -10%, rgba(99,102,241,0.06) 0%, transparent 70%)',
        }}
      />

      <Navbar
        courseCount={courses.length}
        openCount={openCount}
        onAddCourse={() => setShowModal(true)}
        onSettings={() => setShowSettings(true)}
      />

      <main className="relative max-w-5xl mx-auto px-4 sm:px-6 py-8">
        {loading ? (
          <LoadingSkeleton />
        ) : courses.length === 0 ? (
          <EmptyState onAdd={() => setShowModal(true)} />
        ) : (
          <>
            {/* Summary bar */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-4">
                <div className="text-xs text-slate-600">
                  <span className="text-slate-400 font-medium">{courses.length}</span> courses
                </div>
                {openCount > 0 && (
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse-dot" />
                    <span className="text-green-500 font-medium">{openCount} open</span>
                  </div>
                )}
                <div className="text-xs text-slate-700">
                  Refreshes every {POLL_INTERVAL / 1000}s
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-0.5 bg-surface-2 rounded-lg p-0.5 border border-[rgba(99,102,241,0.1)]">
                  <button
                    onClick={() => setView('cards')}
                    className={`px-2.5 py-1 rounded-md text-xs transition-colors ${
                      view === 'cards' ? 'bg-surface text-slate-200' : 'text-slate-600 hover:text-slate-400'
                    }`}
                  >
                    Cards
                  </button>
                  <button
                    onClick={() => setView('week')}
                    className={`px-2.5 py-1 rounded-md text-xs transition-colors ${
                      view === 'week' ? 'bg-surface text-slate-200' : 'text-slate-600 hover:text-slate-400'
                    }`}
                  >
                    Week
                  </button>
                </div>
                <button
                  onClick={() => fetchCourses()}
                  className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-400 transition-colors"
                >
                  <svg width="11" height="11" viewBox="0 0 12 12" fill="none" className="opacity-60">
                    <path d="M10 6A4 4 0 1 1 6 2a4 4 0 0 1 3 1.3L10 2v4H6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  Refresh
                </button>
              </div>
            </div>

            {view === 'week' ? (
              <WeekCalendar courses={courses} />
            ) : (
              /* Course grid */
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {courses.map(course => (
                  <CourseCard
                    key={course.courseId}
                    course={course}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {/* Modals */}
      {showModal && (
        <AddCourseModal
          defaultSeason={defaultSeason}
          onAdd={handleAdd}
          onClose={() => setShowModal(false)}
        />
      )}
      {showSettings && (
        <SettingsDrawer onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}

export default function Page() {
  return (
    <ToastProvider>
      <Dashboard />
    </ToastProvider>
  )
}
