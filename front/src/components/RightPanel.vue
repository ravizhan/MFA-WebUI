<template>
  <n-image v-if="connected" :src="streamUrl" />
  <n-empty v-else description="等待设备连接..." />
  <div class="col-name">实时日志</div>
  <div>
    <n-card hoverable>
      <n-button id="btn" block tertiary type="info" :data-clipboard-text="log"> 复制 </n-button>
      <n-log class="log" ref="logInstRef" :log="log" trim :rows="20" />
    </n-card>
  </div>
</template>
<script setup lang="ts">
import type { LogInst } from "naive-ui"
import Clipboard from "clipboard"
import { useMessage } from "naive-ui"
import { sse } from "../script/sse"
import { ref, onMounted, onUnmounted, watchEffect, nextTick } from "vue"
import { useIndexStore } from "../stores"
import { storeToRefs } from "pinia"

const message = useMessage()
const indexStore = useIndexStore()
const { RunningLog: log, Connected: connected } = storeToRefs(indexStore)
const logInstRef = ref<LogInst | null>(null)
const btnCopy = new Clipboard("#btn")
btnCopy.on("success", () => {
  message.success("复制成功")
})

const handleLog = (data: { message: string }) => {
  const msg = data.message
  indexStore.UpdateLog(msg)
}
sse.addEventListener('log', handleLog)

onMounted(() => {
  watchEffect(() => {
    console.log(log.value)
    if (log.value) {
      nextTick(() => {
        logInstRef.value?.scrollTo({ position: "bottom", silent: true })
      })
    }
  })
})

onUnmounted(() => {
  sse.removeEventListener('log', handleLog)
})

const fps = 60;
const streamUrl = `/api/stream/live?fps=${fps}`;
</script>
