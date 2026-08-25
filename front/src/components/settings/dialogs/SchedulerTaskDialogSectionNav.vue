<template>
  <nav
    class="border-[var(--divider-color)] flex shrink-0 gap-1 overflow-x-auto border-b p-2 md:w-44 md:flex-col md:overflow-y-auto md:overflow-x-hidden md:border-r md:border-b-0 md:p-3"
    :aria-label="t('settings.scheduler.dialog.sections.nav')"
  >
    <NTabs v-model:value="activeSection" type="line" size="small" placement="left" class="w-full">
      <NTabPane v-for="section in sections" :key="section.id" :name="section.id">
        <template #tab>
          <span class="flex items-center gap-2 whitespace-nowrap text-sm">
            <NIcon size="16" class="shrink-0"><component :is="section.icon" /></NIcon>
            <span>{{ section.label }}</span>
          </span>
        </template>
      </NTabPane>
    </NTabs>
  </nav>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NIcon, NTabPane, NTabs } from "naive-ui"
import type { Component } from "vue"

type DialogSection = "basic" | "schedule" | "environment" | "content"

interface DialogSectionOption {
  id: DialogSection
  label: string
  icon: Component
}

const { sections } = defineProps<{
  sections: DialogSectionOption[]
}>()

const activeSection = defineModel<DialogSection>("activeSection", { required: true })
const { t } = useI18n()
</script>
