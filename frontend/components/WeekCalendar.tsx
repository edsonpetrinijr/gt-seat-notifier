'use client'

import type { Course, Section } from '@/types'

const DAY_CHARS = ['M', 'T', 'W', 'R', 'F'] as const
type DayChar = typeof DAY_CHARS[number]
const DAY_LABELS: Record<DayChar, string> = { M: 'Mon', T: 'Tue', W: 'Wed', R: 'Thu', F: 'Fri' }

const COLORS = [
  'bg-indigo-500/20 border-indigo-400/40 text-indigo-200',
  'bg-emerald-500/20 border-emerald-400/40 text-emerald-200',
  'bg-amber-500/20 border-amber-400/40 text-amber-200',
  'bg-rose-500/20 border-rose-400/40 text-rose-200',
  'bg-sky-500/20 border-sky-400/40 text-sky-200',
  'bg-fuchsia-500/20 border-fuchsia-400/40 text-fuchsia-200',
]

interface Block {
  label: string
  day: DayChar
  startMin: number
  endMin: number
  color: string
}

function toMinutes(t: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(t)
  if (!m) return null
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10)
}

interface LaidOutBlock extends Block {
  col: number
  cols: number
}

function layoutOverlaps(dayBlocks: Block[]): LaidOutBlock[] {
  const sorted = [...dayBlocks].sort((a, b) => a.startMin - b.startMin)
  const result: LaidOutBlock[] = []
  let cluster: Block[] = []
  let clusterEnd = -Infinity

  function flush() {
    if (cluster.length === 0) return
    const colEnds: number[] = []
    const assigned = cluster.map(b => {
      let col = colEnds.findIndex(end => end <= b.startMin)
      if (col === -1) {
        col = colEnds.length
        colEnds.push(b.endMin)
      } else {
        colEnds[col] = b.endMin
      }
      return { block: b, col }
    })
    const cols = colEnds.length
    assigned.forEach(({ block, col }) => result.push({ ...block, col, cols }))
    cluster = []
  }

  for (const b of sorted) {
    if (cluster.length > 0 && b.startMin >= clusterEnd) flush()
    cluster.push(b)
    clusterEnd = Math.max(clusterEnd, b.endMin)
  }
  flush()

  return result
}

function buildBlocks(courses: Course[]): Block[] {
  const blocks: Block[] = []
  courses.forEach((course, i) => {
    const color = COLORS[i % COLORS.length]
    const rec = course.recommended
    if (!rec) return
    const parts: Section[] = [rec.lecture, rec.lab].filter((s): s is Section => !!s)
    parts.forEach(section => {
      section.meetings.forEach(m => {
        const start = toMinutes(m.start)
        const end = toMinutes(m.end)
        if (start === null || end === null || !m.days) return
        for (const day of m.days) {
          if (!(DAY_CHARS as readonly string[]).includes(day)) continue
          blocks.push({
            label: `${course.courseId} §${section.sectionId}`,
            day: day as DayChar,
            startMin: start,
            endMin: end,
            color,
          })
        }
      })
    })
  })
  return blocks
}

const DAY_START = 8 * 60
const DAY_END = 21 * 60
const EARLIEST_START = 9 * 60 + 30
const LUNCH_START = 12 * 60
const LUNCH_END = 14 * 60
const LATEST_END = 18 * 60

const PROTECTED_ZONES = [
  { top: 0, bottom: EARLIEST_START },
  { top: LUNCH_START, bottom: LUNCH_END },
  { top: LATEST_END, bottom: DAY_END },
]

export default function WeekCalendar({ courses }: { courses: Course[] }) {
  const blocks = buildBlocks(courses)
  const scheduledIds = new Set(blocks.map(b => b.label.split(' §')[0]))
  const asyncCourses = courses.filter(c => c.recommended && !scheduledIds.has(c.courseId))
  const hours: number[] = []
  for (let h = 8; h <= 21; h++) hours.push(h)
  const totalHeight = DAY_END - DAY_START

  const asyncNote = asyncCourses.length > 0 && (
    <div className="text-[11px] text-slate-600 mt-3 pt-3 border-t border-[rgba(99,102,241,0.08)]">
      No fixed meeting time (async/online): {asyncCourses.map(c => c.courseId).join(', ')}
    </div>
  )

  if (blocks.length === 0) {
    return (
      <div className="bg-surface rounded-2xl border border-[rgba(99,102,241,0.1)] py-16 text-center text-sm text-slate-600">
        No scheduled meeting times to show — recommended sections are TBA or online-only.
        {asyncCourses.length > 0 && (
          <p className="mt-2 text-[11px]">{asyncCourses.map(c => c.courseId).join(', ')}</p>
        )}
      </div>
    )
  }

  return (
    <div className="bg-surface rounded-2xl border border-[rgba(99,102,241,0.1)] p-4 overflow-x-auto">
      <div className="flex items-center gap-1.5 mb-3 text-[11px] text-slate-600">
        <span className="w-2.5 h-2.5 rounded-sm bg-[rgba(120,120,140,0.2)]" />
        Off-limits: before 9:30am, lunch 12–2pm, after 6pm
      </div>
      <div className="min-w-[640px]">
        <div className="flex">
          <div className="w-14 flex-shrink-0" />
          {DAY_CHARS.map(day => (
            <div key={day} className="flex-1 text-center text-xs font-medium text-slate-500 pb-2">
              {DAY_LABELS[day]}
            </div>
          ))}
        </div>

        <div className="flex">
          <div className="w-14 flex-shrink-0 relative" style={{ height: totalHeight }}>
            {hours.map(h => (
              <span
                key={h}
                className="absolute -top-2 right-2 text-[10px] text-slate-600"
                style={{ top: (h * 60 - DAY_START) }}
              >
                {h % 12 === 0 ? 12 : h % 12}{h < 12 ? 'am' : 'pm'}
              </span>
            ))}
          </div>

          {DAY_CHARS.map(day => (
            <div
              key={day}
              className="flex-1 relative border-l border-[rgba(99,102,241,0.08)]"
              style={{ height: totalHeight }}
            >
              {hours.map(h => (
                <div
                  key={h}
                  className="absolute w-full border-t border-[rgba(99,102,241,0.06)]"
                  style={{ top: h * 60 - DAY_START }}
                />
              ))}
              {PROTECTED_ZONES.map((z, idx) => (
                <div
                  key={idx}
                  className="absolute w-full bg-[rgba(120,120,140,0.06)] pointer-events-none"
                  style={{
                    top: Math.max(z.top, DAY_START) - DAY_START,
                    height: Math.min(z.bottom, DAY_END) - Math.max(z.top, DAY_START),
                  }}
                />
              ))}
              {layoutOverlaps(blocks.filter(b => b.day === day)).map((b, idx) => (
                <div
                  key={idx}
                  className={`absolute rounded-md border px-1.5 py-0.5 text-[10px] leading-tight overflow-hidden ${b.color}`}
                  style={{
                    top: b.startMin - DAY_START,
                    height: Math.max(b.endMin - b.startMin, 16),
                    left: `calc(${(b.col / b.cols) * 100}% + 1px)`,
                    width: `calc(${100 / b.cols}% - 2px)`,
                  }}
                  title={b.label}
                >
                  {b.label}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      {asyncNote}
    </div>
  )
}
