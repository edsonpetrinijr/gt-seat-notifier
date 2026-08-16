'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { Settings } from '@/types'
import { useToast } from './Toast'

interface Props {
  onClose: () => void
}

export default function SettingsDrawer({ onClose }: Props) {
  const { toast } = useToast()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {})
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function save() {
    if (!settings) return
    setSaving(true)
    try {
      const updated = await api.saveSettings(settings)
      setSettings(updated)
      toast('Settings saved', 'success')
      onClose()
    } catch {
      toast('Failed to save settings', 'error')
    } finally {
      setSaving(false)
    }
  }

  function update<K extends keyof Settings>(k: K, v: Settings[K]) {
    setSettings(s => s ? { ...s, [k]: v } : s)
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end animate-fade-in">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bg/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="relative w-full max-w-sm h-full bg-surface border-l border-[rgba(99,102,241,0.12)] shadow-modal flex flex-col animate-slide-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-[rgba(99,102,241,0.08)]">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Settings</h2>
            <p className="text-xs text-slate-600 mt-0.5">Notifications & monitoring</p>
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

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {!settings ? (
            <div className="space-y-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="space-y-2">
                  <div className="h-3 w-24 bg-surface-3 rounded animate-pulse" />
                  <div className="h-10 bg-surface-3 rounded-xl animate-pulse" />
                </div>
              ))}
            </div>
          ) : (
            <>
              {/* Notifications toggle */}
              <div className="flex items-center justify-between p-4 bg-surface-2 rounded-xl border border-[rgba(99,102,241,0.08)]">
                <div>
                  <p className="text-sm font-medium text-slate-200">Push Notifications</p>
                  <p className="text-xs text-slate-600 mt-0.5">Via ntfy.sh</p>
                </div>
                <button
                  onClick={() => update('notifications_enabled', !settings.notifications_enabled)}
                  className={`
                    relative w-11 h-6 rounded-full transition-colors duration-200
                    ${settings.notifications_enabled ? 'bg-accent' : 'bg-surface-3'}
                  `}
                >
                  <span className={`
                    absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200
                    ${settings.notifications_enabled ? 'translate-x-5' : 'translate-x-0'}
                  `} />
                </button>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1.5">ntfy Topic</label>
                <input
                  value={settings.ntfy_topic}
                  onChange={e => update('ntfy_topic', e.target.value)}
                  placeholder="gt-alerts-yourname"
                  className="input-field font-mono"
                />
                <p className="text-[11px] text-slate-700 mt-1.5">
                  Subscribe to this topic in the ntfy app to receive alerts.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1.5">ntfy Server</label>
                <input
                  value={settings.ntfy_server}
                  onChange={e => update('ntfy_server', e.target.value)}
                  placeholder="https://ntfy.sh"
                  className="input-field"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1.5">Default Term</label>
                  <input
                    value={settings.term}
                    onChange={e => update('term', e.target.value.replace(/\D/g, ''))}
                    placeholder="202608"
                    className="input-field font-mono"
                    maxLength={6}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1.5">Interval (s)</label>
                  <input
                    type="number"
                    value={settings.interval}
                    onChange={e => update('interval', parseInt(e.target.value) || 30)}
                    min={15}
                    className="input-field font-mono"
                  />
                </div>
              </div>

              <div className="p-3 bg-surface-2 rounded-xl border border-[rgba(99,102,241,0.08)]">
                <p className="text-[11px] text-slate-600 leading-relaxed">
                  <span className="text-slate-500 font-medium">Term codes:</span>{' '}
                  YYYYSS where SS = 02 (Spring) / 05 (Summer) / 08 (Fall).
                  Example: <span className="font-mono text-slate-500">202608</span> = Fall 2026.
                </p>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        {settings && (
          <div className="px-6 py-4 border-t border-[rgba(99,102,241,0.08)] flex gap-3">
            <button onClick={onClose} className="btn-ghost flex-1">Cancel</button>
            <button onClick={save} disabled={saving} className="btn-primary flex-1">
              {saving ? 'Saving…' : 'Save Settings'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
