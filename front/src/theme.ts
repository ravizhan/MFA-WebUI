import type { GlobalThemeOverrides } from "naive-ui";

export const lightThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#2080f0',
    primaryColorHover: '#4098fc',
    primaryColorPressed: '#1060c9',
    borderRadius: '10px',
  },
  Layout: {
    color: '#f5f7fa',
    headerColor: '#ffffff',
    footerColor: '#f5f7fa'
  },
  Card: {
    borderRadius: '12px',
    color: '#ffffff',
    borderColor: '#efeff5' 
  }
}

export const darkThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#2080f0',
    primaryColorHover: '#4098fc',
    primaryColorPressed: '#1060c9',
    borderRadius: '10px',
  },
  Layout: {
    color: '#101014',
    headerColor: '#18181c',
    footerColor: '#101014'
  },
  Card: {
    borderRadius: '12px',
    color: '#18181c',
    borderColor: '#2d2d30'
  }
}
