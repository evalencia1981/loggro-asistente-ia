/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Paleta "Cellar" — consola de bar cálida y oscura
        espresso: {
          950: "#100c08",
          900: "#16110b",
          850: "#1c150e",
          800: "#241b12",
          700: "#33271a",
          600: "#473726",
        },
        sand: {
          50: "#f7efe3",
          100: "#efe3d1",
          300: "#d8c4a8",
          400: "#bfa483",
          500: "#a3855f",
        },
        amber: {
          DEFAULT: "#e8a23a",
          bright: "#f5c563",
          deep: "#c47e22",
        },
        matched: "#5fb98e",
        pending: "#e8804f",
        wine: "#7a2e3a",
      },
      fontFamily: {
        display: ['"Fraunces"', "serif"],
        sans: ['"Hanken Grotesk"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(232,162,58,0.25), 0 18px 50px -12px rgba(232,162,58,0.20)",
        panel: "0 24px 60px -24px rgba(0,0,0,0.8)",
      },
      keyframes: {
        "rise": {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "pour": {
          "0%": { transform: "scaleX(0)" },
          "100%": { transform: "scaleX(1)" },
        },
      },
      animation: {
        rise: "rise 0.55s cubic-bezier(0.22,1,0.36,1) both",
        fade: "fade 0.6s ease both",
        pour: "pour 0.9s cubic-bezier(0.65,0,0.35,1) both",
      },
    },
  },
  plugins: [],
};
