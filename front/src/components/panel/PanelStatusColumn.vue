<template>
  <template v-if="mobileView">
    <n-tabs type="line" animated>
      <n-tab-pane name="preview" :tab="t('panel.preview')">
        <n-card hoverable>
          <n-flex class="pb-[12px]" justify="space-around" :size="[5, 0]">
            <n-select
              v-model:value="fps"
              :placeholder="t('panel.selectFPS')"
              :options="fpsOptions"
              class="w-40"
            />
            <n-button secondary type="info" :disabled="streaming" @click="handleStartStream">
              <template #icon
                ><n-icon><div class="i-mdi-play-circle-outline"></div></n-icon
              ></template>
              {{ t("common.start") }}
            </n-button>
            <n-button secondary type="warning" :disabled="!streaming" @click="handleStopStream">
              <template #icon
                ><n-icon><div class="i-mdi-pause-circle-outline"></div></n-icon
              ></template>
              {{ t("common.pause") }}
            </n-button>
          </n-flex>
          <div ref="streamContainer" class="flex h-50 items-center justify-center bg-gray-1/5">
            <template v-if="connected">
              <n-image v-if="streaming" :src="streamUrl" class="h-auto max-w-full" />
              <n-empty v-else :description="t('panel.previewHint')" />
            </template>
            <n-empty v-else :description="t('panel.connectFirstHint')" />
          </div>
        </n-card>
      </n-tab-pane>
      <n-tab-pane name="log" :tab="t('panel.log')">
        <n-card hoverable>
          <n-button
            class="panel-log-copy-btn"
            block
            tertiary
            type="info"
            :data-clipboard-text="log"
          >
            {{ t("common.copy") }}
          </n-button>
          <n-log class="log" ref="logInstRef" :log="log" trim :rows="9" />
        </n-card>
      </n-tab-pane>
    </n-tabs>
  </template>

  <template v-else>
    <div class="col-name">{{ t("panel.preview") }}</div>
    <n-card hoverable>
      <n-flex class="pb-[12px]" justify="space-around" :size="[5, 0]">
        <n-select
          v-model:value="fps"
          :placeholder="t('panel.selectFPS')"
          :options="fpsOptions"
          class="w-40"
        />
        <n-button secondary type="info" :disabled="streaming" @click="handleStartStream">
          <template #icon
            ><n-icon><div class="i-mdi-play-circle-outline"></div></n-icon
          ></template>
          {{ t("common.start") }}
        </n-button>
        <n-button secondary type="warning" :disabled="!streaming" @click="handleStopStream">
          <template #icon
            ><n-icon><div class="i-mdi-pause-circle-outline"></div></n-icon
          ></template>
          {{ t("common.pause") }}
        </n-button>
      </n-flex>
      <div ref="streamContainer" class="flex h-50 items-center justify-center bg-gray-1/5">
        <template v-if="connected">
          <n-image v-if="streaming" :src="streamUrl" class="h-auto max-w-full" />
          <n-empty v-else :description="t('panel.previewHint')" />
        </template>
        <n-empty v-else :description="t('panel.connectFirstHint')" />
      </div>
    </n-card>

    <div class="col-name">{{ t("panel.log") }}</div>
    <n-card hoverable>
      <n-button class="panel-log-copy-btn" block tertiary type="info" :data-clipboard-text="log">
        {{ t("common.copy") }}
      </n-button>
      <n-log class="log" ref="logInstRef" :log="log" trim :rows="11" />
    </n-card>
  </template>
</template>

<script setup lang="ts">
import Clipboard from "clipboard"
import { storeToRefs } from "pinia"
import type { LogInst } from "naive-ui"
import { useMessage } from "naive-ui"
import { nextTick, onMounted, onUnmounted, ref, watch, watchEffect } from "vue"
import { useI18n } from "vue-i18n"
import { useIndexStore } from "@/stores"
import { useViewport } from "@/utils/viewport/useViewport"

const { t } = useI18n()
const message = useMessage()
const indexStore = useIndexStore()
const { Connected: connected, RunningLog: log } = storeToRefs(indexStore)
const streaming = ref(false)
const fps = ref(30)
const streamUrl = ref("")
const streamContainer = ref<HTMLElement | null>(null)
const logInstRef = ref<LogInst | null>(null)
const { isMobile: mobileView } = useViewport()
let clipboard: Clipboard | null = null

const fpsOptions = [
  { label: "15 FPS", value: 15 },
  { label: "30 FPS", value: 30 },
  { label: "60 FPS", value: 60 },
]

function handleCopySuccess() {
  message.success(t("panel.copySuccess"))
}

function setupClipboard() {
  if (clipboard) {
    clipboard.off("success", handleCopySuccess)
    clipboard.destroy()
  }
  clipboard = new Clipboard(".panel-log-copy-btn")
  clipboard.on("success", handleCopySuccess)
}

onMounted(() => {
  void nextTick().then(() => {
    setupClipboard()
  })

  watchEffect(() => {
    if (log.value) {
      nextTick(() => {
        logInstRef.value?.scrollTo({ position: "bottom", silent: true })
      })
    }
  })
})

function handleStartStream() {
  if (!connected.value) {
    message.error(t("panel.connectFirstHint"))
    return
  }
  streaming.value = true
  streamUrl.value = `/api/stream/live?fps=${fps.value}`
}

function handleStopStream() {
  const img = streamContainer.value?.querySelector("img")
  if (img) {
    img.src = ""
  }
  streaming.value = false
}

watch(connected, (newValue) => {
  if (!newValue && streaming.value) {
    handleStopStream()
  }
})

onUnmounted(() => {
  if (clipboard) {
    clipboard.off("success", handleCopySuccess)
    clipboard.destroy()
    clipboard = null
  }
  handleStopStream()
})
</script>

<style scoped>
.log {
  margin-top: 0.5rem;
  border: 1px solid rgba(140, 140, 140, 0.2);
  border-radius: 8px;
  padding: 0.5rem;
  transition: border-color 0.3s ease;
}
</style>
