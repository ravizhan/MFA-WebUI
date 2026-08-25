<template>
  <!-- Wrapper carries responsive hiding + positioning: naive's .n-card sets
       display:flex (unlayered, beats Tailwind's layered lg:hidden), so the
       breakpoint class must live on a plain div, not the NCard itself. -->
  <div
    class="lg:hidden fixed bottom-4 left-1/2 -translate-x-1/2 z-40"
    style="padding-bottom: calc(0.5rem + env(safe-area-inset-bottom))"
  >
    <NCard
      size="small"
      :bordered="false"
      content-style="display:flex;align-items:center;gap:2px;padding:6px 6px;width:max-content"
      style="
        background: color-mix(in srgb, var(--card-color) 90%, transparent);
        backdrop-filter: blur(8px);
      "
    >
      <NButton
        v-for="item in items"
        :key="item.key"
        quaternary
        :focusable="false"
        :type="activeKey === item.key ? 'primary' : 'default'"
        style="padding: 4px 6px"
        @click="emit('select', item)"
      >
        <div class="flex flex-col items-center gap-0.5 min-w-[2.75rem]">
          <NIcon size="20"><component :is="item.iconComponent" /></NIcon>
          <span class="text-[10px] truncate">{{ item.label }}</span>
        </div>
      </NButton>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import type { Component } from "vue"
import { NButton, NCard, NIcon } from "naive-ui"

export interface DockItem {
  key: string
  label: string
  iconComponent: Component
}

defineProps<{
  items: DockItem[]
  activeKey: string
}>()

const emit = defineEmits<{
  (e: "select", item: DockItem): void
}>()
</script>
