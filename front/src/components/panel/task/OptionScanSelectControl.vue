<template>
  <div class="flex w-full max-w-xs items-center gap-2">
    <NSelect v-model:value="value" size="small" class="flex-1" :options="options" />
    <NButton quaternary circle size="small" :disabled="refreshing" @click="emit('rescan')">
      <template #icon>
        <NIcon size="16" :class="{ 'animate-spin': refreshing }">
          <RefreshOutline />
        </NIcon>
      </template>
    </NButton>
  </div>
</template>

<script setup lang="ts">
import { NButton, NIcon, NSelect } from "naive-ui"
import { RefreshOutline } from "@vicons/ionicons5"

interface SelectOption {
  label: string
  value: string
}

defineProps<{
  options: SelectOption[]
  refreshing: boolean
}>()

const value = defineModel<string | null>("value")

const emit = defineEmits<{
  (event: "rescan"): void
}>()
</script>
