<template>
  <div
    class="lg:hidden fixed bottom-4 left-1/2 -translate-x-1/2 z-40"
    style="padding-bottom: calc(0.5rem + env(safe-area-inset-bottom))"
  >
    <NCard
      :bordered="false"
      content-style="display:flex;align-items:center;gap:2px;padding:4px;width:max-content"
      style="background: transparent; backdrop-filter: blur(5px)"
    >
      <NButton
        v-for="item in items"
        :key="item.key"
        quaternary
        :focusable="false"
        :type="activeKey === item.key ? 'primary' : 'default'"
        style="padding: 2px 4px; --n-color-hover: rgba(46, 51, 56, 0.2); margin: 2px"
        @click="emit('select', item)"
      >
        <div class="flex flex-col items-center gap-0.5 min-w-11">
          <NIcon size="20"><component :is="item.iconComponent" /></NIcon>
          <span class="text-[12px] truncate">{{ item.label }}</span>
        </div>
      </NButton>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import type { Component } from "vue"

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
