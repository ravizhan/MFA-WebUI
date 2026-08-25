<template>
  <NCard
    :bordered="false"
    size="small"
    class="cursor-pointer transition-shadow hover:shadow-md"
    content-style="padding: 12px"
    @click="emit('apply', preset.name)"
  >
    <h3 class="text-sm font-semibold">{{ preset.label }}</h3>
    <p class="text-xs opacity-70 line-clamp-2">{{ preset.description }}</p>
    <div class="flex justify-end mt-2">
      <NTag type="primary" size="small">
        {{ preset.taskCount }} {{ t("panel.preset.taskCount") }}
      </NTag>
    </div>
  </NCard>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NCard, NTag } from "naive-ui"

interface RecipeCardPreset {
  name: string
  label: string
  description: string
  taskCount: number
}

const { t } = useI18n()
const { preset } = defineProps<{ preset: RecipeCardPreset }>()
const emit = defineEmits<{
  (e: "apply", name: string): void
}>()
</script>
