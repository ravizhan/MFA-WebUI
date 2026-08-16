<template>
  <dialog
    ref="dialogRef"
    class="modal modal-bottom sm:modal-middle"
    aria-labelledby="start-conflict-dialog-title"
    @close="handleClose"
  >
    <div class="modal-box w-full max-w-md">
      <!-- Header -->
      <header
        class="border-base-200 flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-5"
      >
        <div class="flex min-w-0 items-center gap-2">
          <Icon icon="mdi:alert-circle" class="text-warning shrink-0 text-xl" aria-hidden="true" />
          <h3 id="start-conflict-dialog-title" class="truncate text-base font-semibold sm:text-lg">
            {{ t("settings.scheduler.conflict.title") }}
          </h3>
        </div>
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-square shrink-0"
          :title="t('common.cancel')"
          :aria-label="t('common.cancel')"
          @click="handleClose"
        >
          <Icon icon="mdi:close" class="text-lg" aria-hidden="true" />
        </button>
      </header>

      <!-- Body -->
      <div class="p-4">
        <div v-if="conflict?.code === 'update_in_progress'" class="alert alert-info">
          <Icon icon="mdi:information-outline" class="shrink-0" aria-hidden="true" />
          <span>{{ t("settings.scheduler.conflict.updateInProgress") }}</span>
        </div>
        <div v-else-if="conflict" class="alert alert-warning">
          <Icon icon="mdi:alert-outline" class="shrink-0" aria-hidden="true" />
          <span>
            {{ t("settings.scheduler.conflict.busyMessage", { name: conflict.active_task_name }) }}
          </span>
        </div>
      </div>

      <!-- Footer -->
      <div class="modal-action">
        <button
          v-if="conflict && conflict.code !== 'update_in_progress'"
          type="button"
          class="btn btn-warning"
          @click="handleStopRestart"
        >
          {{ t("settings.scheduler.conflict.stopAndRestart") }}
        </button>
        <button type="button" class="btn" @click="handleClose">
          {{ t("common.cancel") }}
        </button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { computed, useTemplateRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { Icon } from "@iconify/vue"
import { useDeviceConnectionStore } from "@/stores/device/deviceConnection"

const { t } = useI18n()
const router = useRouter()
const deviceStore = useDeviceConnectionStore()

const dialogRef = useTemplateRef<HTMLDialogElement>("dialogRef")
const conflict = computed(() => deviceStore.startConflict)

watch(
  conflict,
  (value) => {
    const el = dialogRef.value
    if (!el) {
      return
    }
    if (value) {
      if (!el.open) {
        el.showModal()
      }
      return
    }
    if (el.open) {
      el.close()
    }
  },
  { immediate: true },
)

function handleClose() {
  deviceStore.clearStartConflict()
}

async function handleStopRestart() {
  const success = await deviceStore.stopActiveAndRestart()
  if (success) {
    router.push({ name: "logs" })
  }
}
</script>
