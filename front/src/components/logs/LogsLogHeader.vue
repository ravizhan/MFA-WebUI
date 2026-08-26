<template>
  <div class="flex items-center justify-between shrink-0">
    <h2 class="text-base font-semibold flex items-center gap-2">
      <NIcon size="20" style="color: var(--primary-color)">
        <DocumentTextOutline />
      </NIcon>
      {{ t("panel.log") }}
    </h2>
    <div class="flex gap-1">
      <NButton
        quaternary
        circle
        size="small"
        :type="autoScroll ? 'primary' : 'default'"
        :aria-label="autoScroll ? 'Disable auto-scroll' : 'Enable auto-scroll'"
        @click="emit('toggle-auto-scroll')"
      >
        <template #icon>
          <NIcon size="18">
            <component :is="autoScroll ? ChevronDownOutline : ChevronUpOutline" />
          </NIcon>
        </template>
      </NButton>
      <NButton
        quaternary
        circle
        size="small"
        :disabled="!hasLog"
        :aria-label="t('common.copy')"
        :title="t('common.copy')"
        @click="emit('copy')"
      >
        <template #icon>
          <NIcon size="18"><CopyOutline /></NIcon>
        </template>
      </NButton>
      <NButton
        quaternary
        circle
        size="small"
        :disabled="!hasLog"
        aria-label="Download log"
        title="Download log"
        @click="emit('download')"
      >
        <template #icon>
          <NIcon size="18"><DownloadOutline /></NIcon>
        </template>
      </NButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NButton, NIcon } from "naive-ui"
import {
  ChevronDownOutline,
  ChevronUpOutline,
  CopyOutline,
  DocumentTextOutline,
  DownloadOutline,
} from "@vicons/ionicons5"

const { autoScroll, hasLog } = defineProps<{
  autoScroll: boolean
  hasLog: boolean
}>()

const emit = defineEmits<{
  (e: "copy"): void
  (e: "download"): void
  (e: "toggle-auto-scroll"): void
}>()

const { t } = useI18n()
</script>
