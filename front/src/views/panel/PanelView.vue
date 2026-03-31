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
import { computed, onMounted, onUnmounted, ref } from "vue"
import PanelControlColumn from "@/components/panel/PanelControlColumn.vue"
import PanelStatusColumn from "@/components/panel/PanelStatusColumn.vue"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
import TaskSettingsDrawer from "@/components/panel/task/TaskSettingsDrawer.vue"

const MOBILE_BREAKPOINT = 768
const DESKTOP_BREAKPOINT = 1280

const windowWidth = ref(window.innerWidth)
const isMobile = computed(() => windowWidth.value < MOBILE_BREAKPOINT)
const isDesktop = computed(() => windowWidth.value >= DESKTOP_BREAKPOINT)
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

function handleResize() {
  windowWidth.value = window.innerWidth
}

onMounted(() => {
  window.addEventListener("resize", handleResize)
  handleResize()
})

onUnmounted(() => {
  window.removeEventListener("resize", handleResize)
})
</script>
