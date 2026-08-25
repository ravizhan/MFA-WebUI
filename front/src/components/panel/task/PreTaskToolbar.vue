<template>
  <div class="flex items-center justify-between mb-2">
    <span class="text-sm opacity-60">{{ $t("taskConfig.preTasks.description") }}</span>
    <NButton type="primary" size="small" @click="emit('add')">
      <template #icon>
        <NIcon><AddOutline /></NIcon>
      </template>
      {{ $t("taskConfig.preTasks.add") }}
    </NButton>
  </div>
</template>

<script setup lang="ts">
import { NButton, NIcon } from "naive-ui"
import { AddOutline } from "@vicons/ionicons5"

const emit = defineEmits<{
  (event: "add"): void
}>()
</script>
