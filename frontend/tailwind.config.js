/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e6ff",
          500: "#3b6cf6",
          600: "#2b57e0",
          700: "#1f47bf",
          900: "#1a2e6c",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "PingFang SC", "sans-serif"],
      },
    },
  },
  plugins: [],
};
