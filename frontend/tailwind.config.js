/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        stark: {
          navy: "#1B3A6B",
          blue: "#2E75B6",
        },
      },
    },
  },
  plugins: [],
};
