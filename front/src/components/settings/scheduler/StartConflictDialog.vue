<template>
  <dialog v-if="conflict" ref="dialogRef" class="modal modal-middle" @close="onNativeClose">
    <div class="modal-box max-w-md">
      <div class="flex items-start gap-3">
        <Icon icon="mdi:alert-circle" class="text-warning shrink-0 text-2xl" aria-hidden="true" />
        <div class="flex-1">
          <h3 class="font-semibold text-base">
            {{ t("settings.scheduler.conflict.title") }}
          </h3>
          <p class="text-sm opacity-80 mt-1">
            <template v-if="conflict.code === 'update_in_progress'">
              {{ t("settings.scheduler.conflict.messageUpdate") }}
            </template>
            <template v-else>
              {{
                t("settings.scheduler.conflict.message", {
                  taskName: conflict.active_task_name,
                  origin: getOriginLabel(t, conflict.active_origin),
                })
              }}
            </template>
          </p>
        </div>
      </div>
      <div class="modal-action flex justify-end gap-2 mt-4">
        <button
          v-if="conflict.code !== 'update_in_progress'"
          type="button"
          class="btn btn-warning btn-sm"
          @click="handleStopAndStart"
        >
          {{ t("settings.scheduler.conflict.stopAndStart") }}
        </button>
        <button type="button" class="btn btn-ghost btn-sm" @click="handleCancel">
          {{ t("settings.scheduler.conflict.cancel") }}
        </button>
      </div>
    </div>
    <form method="dialog" class="modal-backdrop">
      <button type="submit">{{ t("common.cancel") }}</button>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, useTemplateRef } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { Icon } from "@iconify/vue"
import { useDeviceConnectionStore } from "@/stores"
import { getOriginLabel } from "@/utils/scheduler/display"

const { t } = useI18n()
const router = useRouter()
const deviceStore = useDeviceConnectionStore()
const dialogRef = useTemplateRef<HTMLDialogElement>("dialogRef")
const closingFromUi = ref(false)

const conflict = computed(() => deviceStore.startConflict)

function syncDialogVisibility(open: boolean) {
  const el = dialogRef.value
  if (!el) return
  if (open) {
    if (!el.open) el.showModal()
    return
  }
  if (el.open) el.close()
}

watch(
  conflict,
  async (val) => {
    await nextTick()
    syncDialogVisibility(!!val)
  },
  { immediate: true },
)

async function handleStopAndStart() {
  closingFromUi.value = true
  const restarted = await deviceStore.stopActiveAndRestart()
  if (restarted) {
    await router.push({ name: "logs" })
  }
}

function handleCancel() {
  closingFromUi.value = true
  deviceStore.clearStartConflict()
}

function onNativeClose() {
  if (closingFromUi.value) {
    closingFromUi.value = false
    return
  }
  deviceStore.clearStartConflict()
}
</script>
