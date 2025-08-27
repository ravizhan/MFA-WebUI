import {
  defineConfig,
  presetIcons,
  presetTypography,
  transformerDirectives,
  transformerVariantGroup
} from 'unocss'
import presetWind4 from '@unocss/preset-wind4'

export default defineConfig({
  presets: [
    presetIcons({
      collections: {
        mdi: () => import('@iconify-json/mdi').then(i => i.default)
      }
    }),
    presetTypography(),
    presetWind4()
  ],
  transformers: [
    transformerDirectives(),
    transformerVariantGroup(),
  ],
  rules: [
    ['shadow-3xl', {'box-shadow': '0 0 20px 10px rgba(0, 0, 0, 0.15)'}],
  ],
})