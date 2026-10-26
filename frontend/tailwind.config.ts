import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0d1117",
          900: "#121922",
          850: "#161e29",
          800: "#1c2532",
          700: "#263142",
        },
        line: "#232c3a",
        fg: { DEFAULT: "#d8dee8", muted: "#8592a6", faint: "#566275" },
        accent: "#ecad0a",
        primary: "#209dd7",
        secondary: "#753991",
        up: "#26b36b",
        down: "#e5484d",
      },
      fontFamily: {
        sans: ["Archivo", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: {
        "2xs": ["10.5px", "14px"],
      },
    },
  },
  plugins: [],
};

export default config;
