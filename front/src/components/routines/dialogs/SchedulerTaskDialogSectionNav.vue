<template>
  <nav :aria-label="t('settings.scheduler.dialog.sections.nav')">
    <div class="hidden h-full w-52 shrink-0 overflow-y-auto py-2 md:block">
      <NMenu v-model:value="activeSection" :options="menuOptions" :indent="18" />
    </div>
    <div class="shrink-0 border-b border-(--divider-color) px-2 md:hidden">
      <NTabs v-model:value="activeSection" type="bar" size="medium" :bar-width="0">
        <NTab v-for="section in sections" :key="section.id" :name="section.id">
          <span class="flex items-center gap-1.5">
            <NIcon size="15"><component :is="section.icon" /></NIcon>
            <span>{{ section.label }}</span>
          </span>
        </NTab>
      </NTabs>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, h } from "vue"
import { useI18n } from "vue-i18n"
import { NIcon } from "naive-ui"
import type { MenuOption } from "naive-ui"
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

const menuOptions = computed<MenuOption[]>(() =>
  sections.map((section) => ({
    key: section.id,
    label: section.label,
    icon: () => h(NIcon, { size: 18 }, { default: () => h(section.icon) }),
  })),
)
</script>
