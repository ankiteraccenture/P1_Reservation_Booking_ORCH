/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // MakeMyTrip-inspired palette
        mmt: {
          orange: "#EB2026",
          amber: "#FF7A00",
          blue: "#0084FF",
          navy: "#013B7F",
          bg: "#F2F5FA",
          ink: "#1A1A1A",
          mute: "#6B7280",
          line: "#E5E7EB",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 4px 24px rgba(15, 40, 81, 0.06)",
        raised: "0 10px 30px rgba(15, 40, 81, 0.12)",
      },
    },
  },
  plugins: [],
};
