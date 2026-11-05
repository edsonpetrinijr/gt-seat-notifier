import type { Course, Settings } from '@/types'

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

  addCourse: (body: { courseId: string; season: string }) =>
    req<Course>('/courses', { method: 'POST', body: JSON.stringify(body) }),

  deleteCourse: (courseId: string) =>
    req<{ ok: boolean }>(`/courses/${encodeURIComponent(courseId)}`, { method: 'DELETE' }),

  getSettings: () => req<Settings>('/settings'),

  saveSettings: (settings: Partial<Settings>) =>
    req<Settings>('/settings', { method: 'POST', body: JSON.stringify(settings) }),
}
