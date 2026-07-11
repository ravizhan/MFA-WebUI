<template>
  <div class="flex flex-col lg:flex-row gap-4 logs-view max-w-screen-xl mx-auto">
    <!-- Left: Monitoring (Live Preview) -->
    <div class="flex-1 min-h-0 flex items-center justify-center">
      <div class="card bg-base-100 shadow-xl w-full">
        <div class="card-body p-4 flex flex-col">
          <!-- Header with controls -->
          <div class="flex items-center justify-between mb-3 shrink-0">
            <h2 class="card-title text-base">
              <Icon icon="mdi:monitor" class="text-primary text-xl" />
              {{ t("panel.preview") }}
            </h2>
            <div class="flex gap-2">
              <select v-model="fps" class="select select-bordered select-sm w-24">
                <option :value="15">{{ t("panel.preview-fps.fps15") }}</option>
                <option :value="30">{{ t("panel.preview-fps.fps30") }}</option>
                <option :value="60">{{ t("panel.preview-fps.fps60") }}</option>
              </select>
              <button
                class="btn btn-primary btn-sm"
                :disabled="streaming || !connected"
                @click="handleStartStream"
              >
                <Icon icon="mdi:play-circle-outline" class="text-xl" />
              </button>
              <button
                class="btn btn-warning btn-sm"
                :disabled="!streaming"
                @click="handleStopStream"
              >
                <Icon icon="mdi:pause-circle-outline" class="text-xl" />
              </button>
            </div>
          </div>
          <!-- Stream container fills remaining space -->
          <div
            ref="streamContainer"
            class="aspect-video w-full flex items-center justify-center bg-base-200 rounded-xl overflow-hidden"
          >
            <template v-if="connected">
              <img
                v-if="streaming"
                :src="streamUrl"
                class="h-full w-full object-contain"
                alt="live preview"
              />
              <div v-else class="text-center opacity-50">
                <Icon icon="mdi:video-off" class="text-3xl mx-auto mb-2" />
                <p>{{ t("panel.previewHint") }}</p>
              </div>
            </template>
            <div v-else class="text-center opacity-50">
              <Icon icon="mdi:connection" class="text-3xl mx-auto mb-2" />
              <p>{{ t("panel.connectFirstHint") }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Log Stream -->
    <div class="flex-1 min-h-0">
      <div class="card bg-base-100 shadow-xl h-full logs-log-card">
        <div class="card-body p-4 h-full flex flex-col">
          <div class="flex items-center justify-between mb-3 shrink-0">
            <h2 class="card-title text-base">
              <Icon icon="mdi:file-document-outline" class="text-primary text-xl" />
              {{ t("panel.log") }}
            </h2>
            <div class="flex gap-1">
              <button
                class="btn btn-ghost btn-sm"
                :class="{ 'text-primary': autoScroll }"
                @click="autoScroll = !autoScroll"
              >
                <Icon
                  :icon="autoScroll ? 'mdi:arrow-collapse-down' : 'mdi:arrow-collapse-up'"
                  class="text-lg"
                />
              </button>
              <button class="btn btn-ghost btn-sm" :data-clipboard-text="log" @click="handleCopy">
                <Icon icon="mdi:content-copy" class="text-lg" />
                {{ t("common.copy") }}
              </button>
            </div>
          </div>
          <div
            ref="logContainer"
            class="flex-1 min-h-0 log-panel bg-base-200 rounded-xl p-4 overflow-y-auto"
          >
            <pre v-if="log">{{ log }}</pre>
            <div v-else class="text-center opacity-50 py-12">
              <Icon icon="mdi:text-box-outline" class="text-3xl mx-auto mb-2" />
              <p>{{ t("panel.empty") }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { storeToRefs } from "pinia"
import { nextTick, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { useDeviceConnectionStore, useIndexStore } from "@/stores"

const { t } = useI18n()
const indexStore = useIndexStore()
const deviceStore = useDeviceConnectionStore()
const { Connected: connected, RunningLog: log } = storeToRefs(indexStore)
const streaming = ref(false)
const fps = ref(30)
const streamUrl = ref("")
const streamContainer = useTemplateRef<HTMLElement>("streamContainer")
const logContainer = useTemplateRef<HTMLElement>("logContainer")
const autoScroll = ref(true)

function handleStartStream() {
  if (!connected.value) {
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

function handleCopy() {
  if (!log.value) return
  navigator.clipboard.writeText(log.value).catch(() => {})
}

watch(connected, (newValue) => {
  if (!newValue && streaming.value) {
    handleStopStream()
  }
})

watch(
  log,
  () => {
    if (!autoScroll.value) return
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  },
  { immediate: true },
)

onMounted(() => {
  deviceStore.init()
})

onUnmounted(() => {
  handleStopStream()
  deviceStore.cleanup()
})
</script>

<style scoped>
.logs-view {
  height: calc(100vh - 7rem - 1px);
}
@media (max-width: 1023px) {
  .logs-view {
    height: auto;
  }
  .logs-log-card {
    height: auto !important;
  }
}
</style>
