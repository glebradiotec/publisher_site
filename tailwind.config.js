/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        "primary": "#0D9488",
        "primary-soft": "#5EEAD4",
        "primary-dark": "#115E59",
        "accent": "#0EA5E9",
        "accent-dark": "#0369A1",
        "secondary": "#06B6D4",
        "background-light": "#F8FAFF",
        "background-dark": "#0F172A",
        "surface-light": "#FFFFFF",
        "surface-dark": "#1E293B",
        "text-main": "#0F172A",
        "text-muted": "#475569",
        "soft-teal": "#E0F2FE",
        "soft-cyan": "#DBEAFE",
        "soft-blue": "#EEF2FF",
        "ocean-blue": "#1E3A8A",
      },
      fontFamily: {
        "display": ["Outfit", "sans-serif"],
        "body": ["Plus Jakarta Sans", "sans-serif"],
      },
      borderRadius: {
        "DEFAULT": "0.5rem",
        "lg": "1rem",
        "xl": "1.5rem",
        "2xl": "2rem",
        "3xl": "3rem",
        "full": "9999px"
      },
      boxShadow: {
        'soft': '0 10px 40px -10px rgba(13, 148, 136, 0.1)',
        'glow': '0 0 20px rgba(13, 148, 136, 0.3)',
      }
    },
  },
  corePlugins: {
    preflight: false,
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/container-queries'),
  ],
}
