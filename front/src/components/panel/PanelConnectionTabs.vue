<template>
  <div v-if="mode === 'device'" class="flex flex-wrap gap-2">
    <select
      :value="selectedController"
      class="select select-bordered select-sm flex-1 min-w-[8rem]"
      :disabled="deviceDisabled"
      @change="handleControllerUpdate(getSelectValue($event))"
    >
      <option value="" disabled>{{ t("panel.selectDeviceType") }}</option>
      <option
        v-for="opt in controllerOptions"
        :key="opt.value"
        :value="opt.value"
        :disabled="opt.disabled"
      >
        {{ opt.label }}
      </option>
    </select>
    <input
      v-if="isPlayCover"
      :value="playCoverAddress"
      class="input input-bordered input-sm flex-1 min-w-[10rem]"
      :placeholder="t('panel.playcoverAddress')"
      :disabled="deviceDisabled"
      @input="emit('update:play-cover-address', getInputValue($event))"
    />
    <CreatableSelect
      v-else
      :model-value="selectedDeviceKey"
      :options="deviceOptions"
      :placeholder="t('panel.selectDevice')"
      :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
      class="flex-1 min-w-[10rem]"
      @update:model-value="emit('update:selected-device-key', $event)"
      @open="emit('open-devices')"
      @create="emit('create-device', $event)"
    />
  </div>

  <!-- Resource-only mode: no tabs, no card wrapper -->
  <div v-else-if="mode === 'resource'" class="flex flex-wrap gap-2">
    <select
      :value="resource"
      class="select select-bordered select-sm flex-1 min-w-[12rem]"
      :disabled="resourceDisabled"
      @change="emit('update:resource', getSelectValue($event) || null)"
    >
      <option value="" disabled>{{ t("panel.selectResource") }}</option>
      <option v-for="opt in resourcesList" :key="opt.value" :value="opt.value">
        {{ opt.label }}
      </option>
    </select>
  </div>

  <!-- Tabs mode (default): full card with tab toggle -->
  <div v-else class="space-y-3">
    <div class="card bg-base-200">
      <div class="card-body p-3">
        <div class="tabs tabs-boxed tabs-sm mb-3">
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'device' }"
            @click="activeTab = 'device'"
          >
            {{ t("panel.device") }}
          </a>
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'resource' }"
            @click="activeTab = 'resource'"
          >
            {{ t("panel.resource") }}
          </a>
        </div>

        <div v-if="activeTab === 'device'" class="flex flex-wrap gap-2">
          <select
            :value="selectedController"
            class="select select-bordered select-sm flex-1 min-w-[8rem]"
            :disabled="deviceDisabled"
            @change="handleControllerUpdate(getSelectValue($event))"
          >
            <option value="" disabled>{{ t("panel.selectDeviceType") }}</option>
            <option
              v-for="opt in controllerOptions"
              :key="opt.value"
              :value="opt.value"
              :disabled="opt.disabled"
            >
              {{ opt.label }}
            </option>
          </select>
          <input
            v-if="isPlayCover"
            :value="playCoverAddress"
            class="input input-bordered input-sm flex-1 min-w-[10rem]"
            :placeholder="t('panel.playcoverAddress')"
            :disabled="deviceDisabled"
            @input="emit('update:play-cover-address', getInputValue($event))"
          />
          <CreatableSelect
            v-else
            :model-value="selectedDeviceKey"
            :options="deviceOptions"
            :placeholder="t('panel.selectDevice')"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            class="flex-1 min-w-[10rem]"
            @update:model-value="emit('update:selected-device-key', $event)"
            @open="emit('open-devices')"
            @create="emit('create-device', $event)"
          />
        </div>

        <div v-else class="flex flex-wrap gap-2">
          <select
            :value="resource"
            class="select select-bordered select-sm flex-1 min-w-[12rem]"
            :disabled="resourceDisabled"
            @change="emit('update:resource', getSelectValue($event) || null)"
          >
            <option value="" disabled>{{ t("panel.selectResource") }}</option>
            <option v-for="opt in resourcesList" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import CreatableSelect from "@/components/common/CreatableSelect.vue"

const {
  selectedController,
  selectedDeviceKey,
  playCoverAddress,
  controllerOptions,
  deviceOptions,
  deviceDisabled,
  resourceDisabled,
  selectedControllerDisabled,
  isPlayCover,
  resource,
  resourcesList,
  mode = "tabs",
} = defineProps<{
  selectedController: string | null
  selectedDeviceKey: string | null
  playCoverAddress: string
  controllerOptions: Array<{ label: string; value: string; disabled?: boolean }>
  deviceOptions: Array<{ label: string; value: string; disabled?: boolean }>
  deviceDisabled: boolean
  resourceDisabled: boolean
  selectedControllerDisabled: boolean
  isPlayCover: boolean
  resource: string | null
  resourcesList: Array<{ label: string; value: string }>
  mode?: "device" | "resource" | "tabs"
}>()

const emit = defineEmits<{
  (e: "update:selected-controller", value: string | null): void
  (e: "update:selected-device-key", value: string | null): void
  (e: "update:play-cover-address", value: string): void
  (e: "update:resource", value: string | null): void
  (e: "controller-change"): void
  (e: "open-devices"): void
  (e: "create-device", value: string): void
}>()

const { t } = useI18n()
const activeTab = ref<"device" | "resource">("device")

function handleControllerUpdate(value: string | null) {
  emit("update:selected-controller", value)
  if (value !== selectedController) {
    emit("controller-change")
  }
}

function getSelectValue(event: Event): string {
  const target = event.target
  if (target instanceof HTMLSelectElement) return target.value
  return ""
}

function getInputValue(event: Event): string {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.value
  return ""
}
</script>
