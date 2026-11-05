export type CourseStatus = 'OPEN' | 'WAITLIST' | 'FULL' | 'LOADING' | 'ERROR'

export interface Meeting {
  days: string
  start: string
  end: string
  room: string
}

export interface Section {
  crn: string
  sectionId: string
  parentId: string | null
  credits: number
  meetings: Meeting[]
  seatsAvailable: number | null
  waitlistAvailable: number | null
  enrollmentActual: number | null
  enrollmentMaximum: number | null
  lastUpdated: string
  error: string | null
  status: CourseStatus
}

export interface Combo {
  type: 'single' | 'lecture+lab'
  lecture: Section
  lab: Section | null
  labOptions: Section[]
  status: CourseStatus
  timePenalty: number
}

export interface Course {
  courseId: string
  courseName: string
  term: string
  sections: Section[]
  recommended: Combo | null
  scheduleConflict: boolean
  openCount: number
  waitlistCount: number
  error?: string | null
}

export type Season = 'spring' | 'summer' | 'fall'

export interface Settings {
  ntfy_topic: string
  ntfy_server: string
  term: string
  interval: number
  notifications_enabled: boolean
}

export interface Toast {
  id: string
  message: string
  type: 'success' | 'error' | 'info'
}

export function courseStatus(course: Course): CourseStatus {
  if (course.openCount > 0) return 'OPEN'
  if (course.waitlistCount > 0) return 'WAITLIST'
  if (course.sections.length === 0) return course.error ? 'ERROR' : 'LOADING'
  if (course.sections.some(s => s.status === 'LOADING')) return 'LOADING'
  return 'FULL'
}

export function seasonFromTerm(term: string): Season {
  const code = term.slice(4)
  if (code === '02') return 'spring'
  if (code === '05') return 'summer'
  return 'fall'
}
