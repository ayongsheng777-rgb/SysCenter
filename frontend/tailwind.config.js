/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        ink: '#0f172a',
        panel: '#ffffff',
        panel2: '#f1f5f9',
        edge: '#e2e8f0',
        accent: '#0891b2',
        accent2: '#0e7490',
        ok: '#059669',
        warn: '#d97706',
        danger: '#dc2626'
      }
    }
  },
  plugins: []
}
