'use client'

import { createContext, useCallback, useContext, useRef, useState } from 'react'
import type { Toast } from '@/types'

interface ToastCtx {
  toast: (message: string, type?: Toast['type']) => void
}

const Ctx = createContext<ToastCtx>({ toast: () => {} })

export function useToast() {
  return useContext(Ctx)
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const counter = useRef(0)

  const toast = useCallback((message: string, type: Toast['type'] = 'info') => {
    const id = String(++counter.current)
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500)
  }, [])

  const iconMap = {
    success: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <path d="M3 7.5l3 3 6-6" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    error: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <path d="M3 3l9 9M12 3l-9 9" stroke="#ef4444" strokeWidth="1.5" strokeLinecap="round"/>
      </svg>
    ),
    info: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <circle cx="7.5" cy="7.5" r="5.5" stroke="#818cf8" strokeWidth="1.2"/>
        <path d="M7.5 7v3.5M7.5 4.5v.5" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round"/>
      </svg>
    ),
  }

  const borderMap = {
    success: 'border-green-500/20',
    error:   'border-red-500/20',
    info:    'border-accent/20',
  }

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 items-end pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`
              pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl
              bg-surface-2 border ${borderMap[t.type]} shadow-modal
              text-sm text-slate-200 max-w-sm
              animate-slide-up
            `}
          >
            <span className="shrink-0">{iconMap[t.type]}</span>
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
