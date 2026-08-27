<template>
  <NEl
    tag="div"
    class="h-16 px-4 sticky top-0 z-40 flex items-center"
    style="
      background-color: var(--body-color);
      box-shadow:
        0 10px 15px -3px rgb(0 0 0 / 0.1),
        0 4px 6px -4px rgb(0 0 0 / 0.1);
    "
  >
    <span class="flex-1 min-w-0 truncate text-xl font-bold tracking-wide">{{ name }}</span>
    <div class="hidden lg:flex flex-none">
      <NMenu
        mode="horizontal"
        :value="menuValue"
        :options="menuOptions"
        class="navbar-menu"
        @update:value="onSelect"
      />
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

<style scoped>
/* Horizontal NMenu marks hover/selected with a bottom border and text color.
   MWU wants each item to read as a button: pill background on hover, no border. */
.navbar-menu :deep(.n-menu-item-content) {
  border-radius: var(--n-border-radius);
  margin: 0 4px;
  transition: background-color 0.2s ease;
}

.navbar-menu :deep(.n-menu-item-content:hover),
.navbar-menu :deep(.n-menu-item-content.n-menu-item-content--selected:hover) {
  background-color: var(--n-item-color-hover);
}

.navbar-menu :deep(.n-menu-item-content.n-menu-item-content--selected),
.navbar-menu :deep(.n-menu-item-content.n-menu-item-content--child-active) {
  background-color: var(--n-item-color-active);
}

.navbar-menu :deep(.n-menu-item-content),
.navbar-menu :deep(.n-menu-item-content.n-menu-item-content--selected),
.navbar-menu :deep(.n-menu-item-content.n-menu-item-content--child-active),
.navbar-menu :deep(.n-menu-item-content:hover),
.navbar-menu :deep(.n-menu-item-content.n-menu-item-content--selected:hover) {
  border-bottom: none;
}
</style>
