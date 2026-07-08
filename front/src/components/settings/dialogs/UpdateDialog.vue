<template>
  <div class="modal" :class="{ 'modal-open': showModal }" @click.self="handleClose">
    <div class="modal-box max-w-lg">
      <h3 class="font-bold text-lg">{{ dialogTitle }}</h3>

      <div class="py-4">
        <div v-if="updateState === 'available'">
          <div class="alert alert-info mb-4">
            <Icon icon="mdi:update" class="text-2xl" />
            <span>{{ version_info }}</span>
          </div>
          <div class="card bg-base-200">
            <div class="card-body p-3">
              <h4 class="card-title text-sm">{{ t("settings.update.updateLog") }}</h4>
              <div class="markdown-body max-h-64 overflow-y-auto" v-html="renderedMarkdown" />
            </div>
          </div>
        </div>

        <div v-else-if="isUpdating" class="space-y-3">
          <div class="alert" :class="updateState === 'failed' ? 'alert-error' : 'alert-info'">
            <span>{{ statusMessage }}</span>
          </div>
          <progress
            v-if="updateState !== 'failed' && updateState !== 'success'"
            class="progress progress-primary w-full"
            max="100"
          />
        </div>

        <div v-else-if="updateState === 'success'" class="alert alert-success">
          {{ t("settings.update.updateSuccess") }}
        </div>

        <div v-else-if="updateState === 'failed'" class="alert alert-error">
          <div>
            <div class="font-bold">{{ t("settings.update.updateFailed") }}</div>
            <div>{{ statusMessage }}</div>
          </div>
        </div>
      </div>

      <div class="modal-action">
        <button
          v-if="updateState === 'available'"
          class="btn btn-ghost"
          :disabled="isUpdating"
          @click="handleClose"
        >
          {{ t("settings.update.later") }}
        </button>
        <button
          v-if="updateState === 'available'"
          class="btn btn-primary"
          :disabled="isUpdating"
          @click="handleUpdate"
        >
          <Icon v-if="isUpdating" icon="mdi:loading" class="animate-spin mr-1 text-lg" />
          {{ t("settings.update.updateNow") }}
        </button>
        <button v-if="updateState === 'failed'" class="btn btn-primary" @click="handleClose">
          {{ t("common.confirm") }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { marked } from "marked"
import { performUpdateApi, getUpdateStatusApi, type UpdateInfo } from "@/services/api"
import DOMPurify from "dompurify"
import { tryCatch } from "@/utils/tryCatch"

const { t } = useI18n()

interface Props {
  show: boolean
  updateInfo: UpdateInfo | null
}

const { show, updateInfo } = defineProps<Props>()
const emit = defineEmits<{
  (e: "update:show", value: boolean): void
}>()

const version_info = computed(() => {
  return (
    t("settings.update.currentVersion") +
    ": " +
    (updateInfo?.current_version || "-") +
    " | " +
    t("settings.update.latestVersion") +
    ": " +
    (updateInfo?.latest_version || "-")
  )
})

const showModal = computed({
  get: () => show,
  set: (value) => emit("update:show", value),
})

const updateState = ref<"available" | "downloading" | "updating" | "success" | "failed">(
  "available",
)
const statusMessage = ref("")
const isUpdating = computed(
  () => updateState.value === "downloading" || updateState.value === "updating",
)

const dialogTitle = computed(() => {
  switch (updateState.value) {
    case "available":
      return t("settings.update.newVersion")
    case "downloading":
      return t("settings.update.downloading")
    case "updating":
      return t("settings.update.updating")
    case "success":
      return t("settings.update.updateSuccess")
    case "failed":
      return t("settings.update.updateFailed")
    default:
      return t("settings.update.newVersion")
  }
})

const renderedMarkdown = computed(() => {
  if (!updateInfo?.release_notes) {
    return "<p>" + t("panel.empty") + "</p>"
  }
  const raw = marked.parse(updateInfo.release_notes)
  return typeof raw === "string" ? DOMPurify.sanitize(raw) : ""
})

let pollTimer: number | null = null

const pollUpdateStatus = async () => {
  const [status, err] = await tryCatch(() => getUpdateStatusApi())
  if (err) {
    console.error("Failed to poll update status:", err)
    return
  }

  statusMessage.value = status.message

  switch (status.status) {
    case "downloading":
      updateState.value = "downloading"
      break
    case "updating":
      updateState.value = "updating"
      break
    case "success":
      updateState.value = "success"
      stopPolling()
      waitForBackendRestart()
      break
    case "failed":
      updateState.value = "failed"
      stopPolling()
      break
    case "idle":
      break
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = window.setInterval(() => {
    void pollUpdateStatus()
  }, 1000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const waitForBackendRestart = () => {
  statusMessage.value = t("settings.update.waitingRestart")
  let retries = 0
  const maxRetries = 60

  const checkBackend = async () => {
    const [response, err] = await tryCatch(() => fetch("/api/settings", { method: "GET" }))
    if (err || !response?.ok) {
      return false
    }
    statusMessage.value = t("settings.update.restarting")
    setTimeout(() => {
      window.location.reload()
    }, 1000)
    return true
  }

  const pollBackend = async () => {
    while (retries < maxRetries) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      retries++

      if (await checkBackend()) {
        return
      }
    }

    window.location.reload()
  }

  pollBackend()
}

const handleUpdate = async () => {
  updateState.value = "downloading"
  statusMessage.value = t("settings.update.downloading")

  const [result, err] = await tryCatch(() => performUpdateApi())
  if (err) {
    updateState.value = "failed"
    statusMessage.value = String(err)
    console.error("Failed to perform update:", err)
    return
  }

  if (result.status === "success") {
    startPolling()
    return
  }
  updateState.value = "failed"
  statusMessage.value = result.message || t("settings.update.updateFailed")
}

const handleClose = () => {
  showModal.value = false
  stopPolling()
}

watch(
  () => show,
  (newShow) => {
    if (newShow) {
      updateState.value = "available"
      statusMessage.value = ""
      return
    }
    stopPolling()
  },
)

onUnmounted(() => {
  stopPolling()
})
</script>
