import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "monospace"],
      },
      colors: {
        archon: {
          bg:             "#080B12",
          surface:        "#0D1117",
          surface2:       "#111827",
          border:         "#161B26",
          border2:        "#1F2937",
          accent:         "#06B6D4",
          "accent-hover": "#0EA5E9",
          success:        "#10B981",
          warning:        "#F59E0B",
          danger:         "#F43F5E",
          text:           "#E2E8F0",
          muted:          "#475569",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
