import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#0f766e",
        "primary-dark": "#0d9488",
        surface: "#f8fafc",
        "surface-dark": "#1e293b",
        border: "#e2e8f0",
      },
      fontFamily: {
        sans: [
          '"Noto Sans KR"',
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [typography],
};

export default config;
