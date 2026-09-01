/** Design tokens per Docs/Frontend.md §10 — government system of record, no gradients. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#FFFFFF',
        surface: '#F6F7F9',
        border: '#D9DEE5',
        ink: '#14213D',
        muted: '#5B6675',
        accent: '#1F4E9C',
        accent2: '#B9770E',
        ok: '#2E7D32',
        amber: '#C77700',
        red: '#B3261E',
        breached: '#1B1B1B',
      },
      borderRadius: { DEFAULT: '4px' },
      fontFamily: {
        sans: ['"Noto Sans"', '"Noto Sans Devanagari"', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
