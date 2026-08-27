<template>
  <div v-if="mode === 'device'" class="flex flex-wrap gap-2">
    <NSelect
      :value="selectedController"
      :options="controllerOptions"
      :placeholder="t('panel.selectDeviceType')"
      :disabled="deviceDisabled"
      class="flex-1 min-w-[8rem]"
      @update:value="handleControllerUpdate"
    />
    <NInput
      v-if="isPlayCover"
      :value="playCoverAddress"
      :placeholder="t('panel.playcoverAddress')"
      :disabled="deviceDisabled"
      class="flex-1 min-w-[10rem]"
      @update:value="emit('update:play-cover-address', $event)"
    />
    <NSelect
      v-else
      filterable
      tag
      :value="selectedDeviceKey"
      :options="deviceOptions"
      :placeholder="t('panel.selectDevice')"
      :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
      class="flex-1 min-w-[10rem]"
      :on-create="(label: string) => ({ label, value: label })"
      @update:value="handleDeviceSelect"
      @update:show="(show: boolean) => show && emit('open-devices')"
    />
  </div>

  <!-- Resource-only mode: no tabs, no card wrapper -->
  <div v-else-if="mode === 'resource'" class="flex flex-wrap gap-2">
    <NSelect
      :value="resource"
      :options="resourcesList"
      :placeholder="t('panel.selectResource')"
      :disabled="resourceDisabled"
      class="flex-1 min-w-[12rem]"
      @update:value="emit('update:resource', $event)"
    />
  </div>

  <!-- Tabs mode (default): full card with tab toggle -->
  <NCard v-else size="small" content-style="padding: 12px">
    <NTabs v-model:value="activeTab" type="segment" size="small" class="mb-3">
      <NTabPane name="device" :tab="t('panel.device')" />
      <NTabPane name="resource" :tab="t('panel.resource')" />
    </NTabs>

    <div v-if="activeTab === 'device'" class="flex flex-wrap gap-2">
      <NSelect
        :value="selectedController"
        :options="controllerOptions"
        :placeholder="t('panel.selectDeviceType')"
        :disabled="deviceDisabled"
        class="flex-1 min-w-[8rem]"
        @update:value="handleControllerUpdate"
      />
      <NInput
        v-if="isPlayCover"
        :value="playCoverAddress"
        :placeholder="t('panel.playcoverAddress')"
        :disabled="deviceDisabled"
        class="flex-1 min-w-[10rem]"
        @update:value="emit('update:play-cover-address', $event)"
      />
      <NSelect
        v-else
        filterable
        tag
        :value="selectedDeviceKey"
        :options="deviceOptions"
        :placeholder="t('panel.selectDevice')"
        :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
        class="flex-1 min-w-[10rem]"
        :on-create="(label: string) => ({ label, value: label })"
        @update:value="handleDeviceSelect"
        @update:show="(show: boolean) => show && emit('open-devices')"
      />
    </div>

    <div v-else class="flex flex-wrap gap-2">
      <NSelect
        :value="resource"
        :options="resourcesList"
        :placeholder="t('panel.selectResource')"
        :disabled="resourceDisabled"
        class="flex-1 min-w-[12rem]"
        @update:value="emit('update:resource', $event)"
      />
    </div>
  </NCard>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"

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

// Device-instance select: a value that is not one of the backend-provided
// options is a brand-new (user-typed) entry — route it through the create
// flow (side effect) instead of a plain select.
function handleDeviceSelect(value: string | null) {
  if (value && !deviceOptions.some((opt) => opt.value === value)) {
    emit("create-device", value)
    return
  }
  emit("update:selected-device-key", value)
}
</script>
