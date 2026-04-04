<template>
  <n-layout class="px-1 pt-3 h-[85vh] xl:h-[80vh]">
    <n-grid :cols="gridCols" x-gap="20" y-gap="20" class="px-2">
      <n-grid-item>
        <PanelControlColumn />
      </n-grid-item>
      <n-grid-item v-if="!isMobile">
        <PanelTaskColumn />
      </n-grid-item>
      <n-grid-item :span="statusSpan">
        <PanelStatusColumn />
      </n-grid-item>
    </n-grid>

    <TaskSettingsDrawer v-if="isMobile" />
  </n-layout>
</template>

<script setup lang="ts">
import { computed } from "vue"
import PanelControlColumn from "@/components/panel/PanelControlColumn.vue"
import PanelStatusColumn from "@/components/panel/PanelStatusColumn.vue"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
import TaskSettingsDrawer from "@/components/panel/task/TaskSettingsDrawer.vue"
import { useViewport } from "@/utils/viewport/useViewport"

const { isMobile, isDesktop } = useViewport()
const gridCols = computed(() => {
  if (isDesktop.value) {
    return 3
  }
  if (isMobile.value) {
    return 1
  }
  return 2
})
const statusSpan = computed(() => {
  if (isDesktop.value) {
    return 1
  }
  return gridCols.value
})
</script>
