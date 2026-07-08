<template>
  <div
    class="card bg-base-200 hover:bg-base-300 transition-colors cursor-pointer group"
    @click="emit('apply', preset.name)"
  >
    <div class="card-body p-3">
      <h3 class="card-title text-sm group-hover:text-primary transition-colors">
        {{ preset.label }}
      </h3>
      <p class="text-xs opacity-70 line-clamp-2">{{ preset.description }}</p>
      <div class="card-actions justify-end mt-2">
        <span class="badge badge-primary badge-sm">
          {{ preset.taskCount }} {{ t("panel.preset.taskCount") }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"

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
