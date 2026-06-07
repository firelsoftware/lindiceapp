/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        lindice: {
          blue: "#4d63b7",
          ink: "#17203b",
          mist: "#9fb5ca",
          purple: "#7a2d84",
          soft: "#eef3ff",
          line: "#d8e1f2",
        },
      },
      boxShadow: {
        glow: "0 24px 80px rgba(23, 32, 59, 0.18)",
      },
      fontFamily: {
        display: ["Georgia", "Times New Roman", "serif"],
        body: ["Segoe UI", "Arial", "sans-serif"],
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(18px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 700ms ease forwards",
      },
    },
  },
  plugins: [],
};
