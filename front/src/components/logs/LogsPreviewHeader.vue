<template>
  <div class="flex items-center justify-between shrink-0">
    <h2 class="text-base font-semibold flex items-center gap-2">
      <NIcon size="20" style="color: var(--primary-color)">
        <DesktopOutline />
      </NIcon>
      {{ t("panel.preview") }}
    </h2>
    <div class="flex gap-2">
      <NSelect
        :value="fps"
        :options="fpsOptions"
        size="small"
        style="width: 110px"
        @update:value="handleFpsUpdate"
      />
      <NButton
        type="primary"
        size="small"
        circle
        :disabled="streaming || !connected"
        @click="emit('start')"
      >
        <template #icon>
          <NIcon size="20"><PlayCircleOutline /></NIcon>
        </template>
      </NButton>
      <NButton type="warning" size="small" circle :disabled="!streaming" @click="emit('stop')">
        <template #icon>
          <NIcon size="20"><PauseCircleOutline /></NIcon>
        </template>
      </NButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { DesktopOutline, PauseCircleOutline, PlayCircleOutline } from "@vicons/ionicons5"

const { connected, fps, fpsOptions, streaming } = defineProps<{
  connected: boolean
  fps: number
  fpsOptions: Array<{ label: string; value: number }>
  streaming: boolean
}>()

const emit = defineEmits<{
  (e: "start"): void
  (e: "stop"): void
  (e: "update:fps", value: number): void
}>()

const { t } = useI18n()

function handleFpsUpdate(value: number | null) {
  if (value === null) return
  emit("update:fps", value)
}
</script>
