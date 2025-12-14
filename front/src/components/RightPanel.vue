<template>
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
import { useMessage, useDialog } from "naive-ui"
import { ws } from "../script/ws.ts"
import { ref, onMounted, watchEffect, nextTick } from "vue"
import { Websocket, WebsocketEvent } from "websocket-ts"
import { useIndexStore } from "../stores"
import { storeToRefs } from "pinia"

const dialog = useDialog()
const message = useMessage()
const indexStore = useIndexStore()
const log = storeToRefs(indexStore).RunningLog
const logInstRef = ref<LogInst | null>(null)
const btnCopy = new Clipboard("#btn")
btnCopy.on("success", () => {
  message.success("复制成功")
})

function is_now(date_string: string) {
  function formatDate(date: Date) {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, "0")
    const day = String(date.getDate()).padStart(2, "0")
    const hours = String(date.getHours()).padStart(2, "0")
    const minutes = String(date.getMinutes()).padStart(2, "0")
    const seconds = String(date.getSeconds()).padStart(2, "0")
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
  }
  return date_string === formatDate(new Date())
}

const getsocketData = (i: Websocket, ev: MessageEvent) => {
  const data: string = ev.data
  if (data === "ping") {
    return
  }
  indexStore.UpdateLog(data)
  if (data.includes("请求接管") && is_now(data.split(" ")[0] + " " + data.split(" ")[1])) {
    message.warning(data)
    new Notification("请求接管", {
      body: data + "\n" + "完成接管后请点击确定",
    })
    dialog.warning({
      title: "请求接管",
      content: data + "\n" + "完成接管后请点击确定",
      positiveText: "确定",
      closable: false,
      maskClosable: false,
      onPositiveClick: () => {
        fetch("/api/continue", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        })
          .then((res) => res.json())
          .then((data) => {
            if (data["status"] === "success") {
              message.success("正在恢复任务")
            } else {
              message.error(data["message"])
            }
          })
      },
    })
  }
}
ws.addEventListener(WebsocketEvent.message, getsocketData)

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
</script>
