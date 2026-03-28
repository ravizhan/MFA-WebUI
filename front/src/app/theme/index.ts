import type { GlobalThemeOverrides } from "naive-ui"

const commonThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#2080f0",
    primaryColorHover: "#4098fc",
    primaryColorPressed: "#1060c9",
    borderRadius: "10px",
  },
  Switch: {
    railColorActive: "#2080f0",
  },
  Anchor: {
    linkFontSize: "0.95rem",
  },
}

export const lightThemeOverrides: GlobalThemeOverrides = {
  ...commonThemeOverrides,
  Layout: {
    color: "#f5f7fa",
    headerColor: "#ffffff",
    footerColor: "#f5f7fa",
  },
  Card: {
    borderRadius: "12px",
    color: "#ffffff",
    borderColor: "#efeff5",
    paddingMedium: "19px 12px 15px",
  },
}

export const darkThemeOverrides: GlobalThemeOverrides = {
  ...commonThemeOverrides,
  Layout: {
    color: "#101014",
    headerColor: "#18181c",
    footerColor: "#101014",
  },
  Card: {
    borderRadius: "12px",
    color: "#18181c",
    borderColor: "#2d2d30",
    paddingMedium: "19px 12px 15px",
  },
}
