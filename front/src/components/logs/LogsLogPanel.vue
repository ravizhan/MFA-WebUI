<template>
  <NEl
    tag="div"
    class="flex-1 min-h-0 log-panel rounded-xl overflow-hidden"
    style="background: var(--card-color)"
  >
    <div ref="logContainer" class="h-full w-full p-4 overflow-y-auto">
      <pre v-if="log">{{ log }}</pre>
      <div v-else class="text-center opacity-50 py-12">
        <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
          <DocumentOutline />
        </NIcon>
        <p>{{ t("panel.empty") }}</p>
      </div>
    </div>
  </NEl>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NEl, NIcon } from "naive-ui"
import { DocumentOutline } from "@vicons/ionicons5"
import { useTemplateRef } from "vue"

const { log } = defineProps<{
  log: string
}>()

const { t } = useI18n()
const logContainer = useTemplateRef<HTMLElement>("logContainer")

function scrollToBottom() {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

defineExpose({ scrollToBottom })
</script>
