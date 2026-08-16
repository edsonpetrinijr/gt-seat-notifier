import type { Course, Section, Settings } from '@/types'

// const BASE = 'https://classes-o2nm.onrender.com'
const BASE = 'http://localhost:8080'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
  return data as T
}

export const api = {
  getCourses: () => req<Course[]>('/courses'),

  addCourse: (body: { crn: string; term: string; name: string }) =>
    req<Course>('/courses', { method: 'POST', body: JSON.stringify(body) }),

  deleteCourse: (crn: string) =>
    req<{ ok: boolean }>(`/courses/${crn}`, { method: 'DELETE' }),

  getSettings: () => req<Settings>('/settings'),

  saveSettings: (settings: Partial<Settings>) =>
    req<Settings>('/settings', { method: 'POST', body: JSON.stringify(settings) }),

  getSections: (term: string, course: string) =>
    req<{ sections: Section[]; warnings: string[] }>(
      `/sections?term=${encodeURIComponent(term)}&course=${encodeURIComponent(course)}`
    ),
}
