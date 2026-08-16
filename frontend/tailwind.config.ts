import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg:          '#05050f',
        surface:     '#0c0c1e',
        'surface-2': '#12122b',
        'surface-3': '#1a1a38',
        accent:      '#6366f1',
        'accent-2':  '#818cf8',
      },
      borderColor: {
        DEFAULT: 'rgba(99,102,241,0.12)',
      },
      boxShadow: {
        card: '0 0 0 1px rgba(99,102,241,0.1), 0 4px 24px rgba(0,0,0,0.6)',
        'card-hover': '0 0 0 1px rgba(99,102,241,0.2), 0 8px 40px rgba(0,0,0,0.8), 0 0 40px rgba(99,102,241,0.06)',
        'glow-green': '0 0 0 1px rgba(34,197,94,0.2), 0 4px 24px rgba(0,0,0,0.6), 0 0 30px rgba(34,197,94,0.06)',
        'glow-green-hover': '0 0 0 1px rgba(34,197,94,0.3), 0 8px 40px rgba(0,0,0,0.8), 0 0 50px rgba(34,197,94,0.1)',
        modal: '0 0 0 1px rgba(99,102,241,0.15), 0 25px 60px rgba(0,0,0,0.9)',
      },
      animation: {
        'fade-in':   'fadeIn 0.15s ease-out',
        'slide-up':  'slideUp 0.25s ease-out',
        'slide-in':  'slideIn 0.3s cubic-bezier(0.16,1,0.3,1)',
        'pop':       'pop 0.15s ease-out',
        'pulse-dot': 'pulseDot 2s ease-in-out infinite',
        'count-in':  'countIn 0.3s cubic-bezier(0.34,1.56,0.64,1)',
      },
      keyframes: {
        fadeIn:   { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp:  { from: { opacity: '0', transform: 'translateY(10px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideIn:  { from: { opacity: '0', transform: 'translateX(100%)' }, to: { opacity: '1', transform: 'translateX(0)' } },
        pop:      { '0%': { transform: 'scale(0.95)' }, '60%': { transform: 'scale(1.02)' }, '100%': { transform: 'scale(1)' } },
        pulseDot: { '0%,100%': { opacity: '1', transform: 'scale(1)' }, '50%': { opacity: '0.4', transform: 'scale(0.8)' } },
        countIn:  { from: { opacity: '0', transform: 'scale(0.7) translateY(4px)' }, to: { opacity: '1', transform: 'scale(1) translateY(0)' } },
      },
    },
  },
}

export default config
