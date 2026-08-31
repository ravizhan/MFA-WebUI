<template>
  <div class="flex w-full max-w-sm flex-col gap-2">
    <div v-for="hotkey in option.hotkeys" :key="hotkey.name" class="flex flex-col gap-1">
      <span class="text-xs opacity-60">{{ resolveHotkeyLabel(hotkey.label, hotkey.name) }}</span>
      <NInput
        size="small"
        readonly
        :value="capturingName === hotkey.name ? '' : getHotkeyValue(hotkey.name)"
        :placeholder="capturingName === hotkey.name ? t('option.hotkeyCapturing') : undefined"
        @focus="capturingName = hotkey.name"
        @blur="handleBlur(hotkey.name)"
        @keydown="handleKeydown(hotkey.name, $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { HotkeyOption } from "@/types/interfaceModel"
import { buildHotkeyCombo } from "@/utils/hotkey"
import { resolveInterfaceText } from "@/utils/interface/content"

const { option, value } = defineProps<{
  option: HotkeyOption
  value: Record<string, string>
}>()

const emit = defineEmits<{
  (event: "update:value", value: Record<string, string>): void
}>()

const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()
const capturingName = ref<string | null>(null)

function resolveHotkeyLabel(label: string | undefined, fallback: string): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

function getHotkeyValue(name: string): string {
  return value[name] ?? ""
}

function handleBlur(name: string): void {
  if (capturingName.value === name) {
    capturingName.value = null
  }
}

function handleKeydown(name: string, event: KeyboardEvent): void {
  event.preventDefault()
  const combo = buildHotkeyCombo(event)
  if (!combo) return
  emit("update:value", { ...value, [name]: combo })
}
</script>
