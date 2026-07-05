<template>
  <n-card content-style="padding: 0.75rem;" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" :tab="t('panel.device')">
        <n-flex class="pb-[12px]" :wrap="true" :size="[12, 12]">
          <n-select
            :value="selectedController"
            :placeholder="t('panel.selectDeviceType')"
            :options="controllerOptions"
            :loading="loading"
            :disabled="deviceDisabled"
            class="min-w-[8rem] flex-1"
            @update:value="handleControllerUpdate"
          />
          <n-input
            v-if="isPlayCover"
            :value="playCoverAddress"
            :placeholder="t('panel.playcoverAddress')"
            :disabled="deviceDisabled"
            class="min-w-[10rem] flex-1"
            @update:value="(value: string) => emit('update:playCoverAddress', value)"
          />
          <n-select
            v-else
            :value="selectedDeviceKey"
            :placeholder="t('panel.selectDevice')"
            :options="deviceOptions"
            :loading="loading"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            filterable
            tag
            clearable
            class="min-w-[10rem] flex-1"
            @update:value="(value: string | null) => emit('update:selectedDeviceKey', value)"
          />
          <n-button
            strong
            secondary
            type="info"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            @click="emit('refresh-devices')"
          >
            {{ t("panel.refresh") }}
          </n-button>
        </n-flex>
      </n-tab-pane>

      <n-tab-pane name="resource" :tab="t('panel.resource')">
        <n-flex class="pb-[12px]" :wrap="true" :size="[12, 12]">
          <n-select
            :value="resource"
            :placeholder="t('panel.selectResource')"
            :options="resourcesList"
            :loading="loading"
            :disabled="resourceDisabled"
            clearable
            class="min-w-[12rem] flex-1"
            @update:value="(value: string | null) => emit('update:resource', value)"
          />
        </n-flex>
      </n-tab-pane>
    </n-tabs>
  </n-card>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import type { SelectOption, SelectGroupOption } from "naive-ui"

const props = defineProps<{
  selectedController: string | null
  selectedDeviceKey: string | null
  playCoverAddress: string
  controllerOptions: Array<{ label: string; value: string; disabled?: boolean }>
  deviceOptions: Array<SelectOption | SelectGroupOption>
  loading: boolean
  deviceDisabled: boolean
  resourceDisabled: boolean
  selectedControllerDisabled: boolean
  isPlayCover: boolean
  resource: string | null
  resourcesList: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{
  (e: "update:selectedController", value: string | null): void
  (e: "update:selectedDeviceKey", value: string | null): void
  (e: "update:playCoverAddress", value: string): void
  (e: "update:resource", value: string | null): void
  (e: "controller-change"): void
  (e: "refresh-devices"): void
}>()

const { t } = useI18n()

function handleControllerUpdate(value: string | null) {
  emit("update:selectedController", value)
  if (value !== props.selectedController) {
    emit("controller-change")
  }
}
</script>
