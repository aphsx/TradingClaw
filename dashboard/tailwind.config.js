/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: '#0a0a0f', card: '#12121a', hover: '#1a1a24' },
        border: { DEFAULT: '#1e1e2e', light: '#2a2a3a' },
      }
    },
  },
  plugins: [],
}
