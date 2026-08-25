<template>
  <NEl
    tag="div"
    class="aspect-video w-full flex items-center justify-center rounded-xl overflow-hidden"
    style="background: var(--card-color)"
  >
    <div class="h-full w-full flex items-center justify-center">
      <template v-if="connected">
        <img
          v-if="streaming"
          ref="streamImage"
          :src="streamUrl"
          class="h-full w-full object-contain"
          alt="live preview"
        />
        <div v-else class="text-center opacity-50">
          <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
            <VideocamOffOutline />
          </NIcon>
          <p>{{ t("panel.previewHint") }}</p>
        </div>
      </template>
      <div v-else class="text-center opacity-50">
        <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
          <LinkOutline />
        </NIcon>
        <p>{{ t("panel.connectFirstHint") }}</p>
      </div>
    </div>
  </NEl>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NEl, NIcon } from "naive-ui"
import { LinkOutline, VideocamOffOutline } from "@vicons/ionicons5"
import { useTemplateRef } from "vue"

const { connected, streaming, streamUrl } = defineProps<{
  connected: boolean
  streaming: boolean
  streamUrl: string
}>()

const { t } = useI18n()
const streamImage = useTemplateRef<HTMLImageElement>("streamImage")

function clearStream() {
  const img = streamImage.value
  if (img) {
    img.src = ""
  }
}

defineExpose({ clearStream })
</script>
