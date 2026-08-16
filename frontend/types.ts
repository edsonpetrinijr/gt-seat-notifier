export interface Section {
  crn: string
  section_id: string
  course_id: string
  course_name: string
}

export interface Course {
  crn: string
  term: string
  name: string
  seatsAvailable: number | null
  waitlistAvailable: number | null
  enrollmentActual: number | null
  enrollmentMaximum: number | null
  lastUpdated: string
  error: string | null
}

export type CourseStatus = 'OPEN' | 'WAITLIST' | 'FULL' | 'LOADING' | 'ERROR'

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

export function getCourseStatus(course: Course): CourseStatus {
  if (course.error) return 'ERROR'
  if (course.seatsAvailable === null) return 'LOADING'
  if (course.seatsAvailable > 0) return 'OPEN'
  if ((course.waitlistAvailable ?? 0) > 0) return 'WAITLIST'
  return 'FULL'
}
