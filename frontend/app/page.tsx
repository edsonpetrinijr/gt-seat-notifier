'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Course } from '@/types'
import { getCourseStatus } from '@/types'
import Navbar from '@/components/Navbar'
import CourseCard from '@/components/CourseCard'
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
  const [defaultTerm, setDefaultTerm]   = useState('202608')
  const [showModal, setShowModal]       = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const prevDataRef = useRef<Record<string, number | null>>({})

  const fetchCourses = useCallback(async (silent = false) => {
    try {
      const data = await api.getCourses()

      // Detect newly opened seats
      data.forEach(c => {
        const prev = prevDataRef.current[c.crn]
        const curr = c.seatsAvailable
        if (prev !== undefined && prev !== null && prev === 0 && curr !== null && curr > 0) {
          toast(`${c.name} — seat opened!`, 'success')
        }
        prevDataRef.current[c.crn] = curr
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
    api.getSettings().then(s => setDefaultTerm(s.term)).catch(() => {})

    const id = setInterval(() => fetchCourses(true), POLL_INTERVAL)
    return () => clearInterval(id)
  }, [fetchCourses])

  function handleAdd(course: Course) {
    setCourses(prev => [...prev, course])
    prevDataRef.current[course.crn] = course.seatsAvailable
    toast(`${course.name} added`, 'success')
  }

  async function handleDelete(crn: string) {
    const course = courses.find(c => c.crn === crn)
    try {
      await api.deleteCourse(crn)
      setCourses(prev => prev.filter(c => c.crn !== crn))
      delete prevDataRef.current[crn]
      toast(`${course?.name ?? crn} removed`, 'info')
    } catch {
      toast('Failed to remove course', 'error')
    }
  }

  const openCount = courses.filter(c => getCourseStatus(c) === 'OPEN').length

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

            {/* Course grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {courses.map(course => (
                <CourseCard
                  key={course.crn}
                  course={course}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          </>
        )}
      </main>

      {/* Modals */}
      {showModal && (
        <AddCourseModal
          defaultTerm={defaultTerm}
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
