<template>
  <NEl
    tag="div"
    class="h-14 px-4 sticky top-0 z-40 flex items-center"
    style="
      background: var(--card-color);
      box-shadow:
        0 10px 15px -3px rgb(0 0 0 / 0.1),
        0 4px 6px -4px rgb(0 0 0 / 0.1);
    "
  >
    <div class="flex-1 min-w-0">
      <span class="text-xl font-bold tracking-wide" style="color: var(--primary-color)">{{
        name
      }}</span>
    </div>
    <div class="hidden lg:flex flex-none">
      <NMenu mode="horizontal" :value="menuValue" :options="menuOptions" @update:value="onSelect" />
    </div>
    <div class="flex-1 flex justify-end gap-2">
      <!-- Dark mode toggle -->
      <NButton quaternary circle @click="emit('toggle-dark')">
        <template #icon>
          <NIcon size="20">
            <MoonOutline v-if="isDark" />
            <SunnyOutline v-else />
          </NIcon>
        </template>
      </NButton>
    </div>
  </NEl>
</template>

<script setup lang="ts">
import { NButton, NEl, NIcon, NMenu } from "naive-ui"
import type { MenuOption } from "naive-ui"
import { MoonOutline, SunnyOutline } from "@vicons/ionicons5"

defineProps<{
  name: string
  isDark: boolean
  menuValue: string
  menuOptions: MenuOption[]
}>()

const emit = defineEmits<{
  (e: "select", key: string): void
  (e: "toggle-dark"): void
}>()

function onSelect(key: string) {
  emit("select", key)
}
</script>
