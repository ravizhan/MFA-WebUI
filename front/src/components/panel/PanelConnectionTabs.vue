<template>
  <n-card content-style="padding: 0;margin: 5px" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" :tab="t('panel.device')">
        <n-flex class="pb-[12px]" :wrap="false">
          <n-select
            :value="selectedController"
            :placeholder="t('panel.selectDeviceType')"
            :options="controllerOptions"
            :loading="loading"
            :disabled="deviceDisabled"
            class="max-w-35%"
            @update:value="handleControllerUpdate"
          />
          <n-input
            v-if="isPlayCover"
            :value="playCoverAddress"
            :placeholder="t('panel.playcoverAddress')"
            :disabled="deviceDisabled"
            class="max-w-45%"
            @update:value="(value: string) => emit('update:playCoverAddress', value)"
          />
          <n-select
            v-else
            :value="selectedDeviceKey"
            :placeholder="t('panel.selectDevice')"
            :options="deviceOptions"
            :loading="loading"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            class="max-w-45%"
            @update:value="(value: string | null) => emit('update:selectedDeviceKey', value)"
            @click="emit('refresh-devices')"
          />
          <n-button
            strong
            secondary
            type="info"
            :disabled="deviceDisabled"
            @click="emit('connect-devices')"
          >
            {{ t("panel.connect") }}
          </n-button>
        </n-flex>
      </n-tab-pane>

      <n-tab-pane name="resource" :tab="t('panel.resource')">
        <n-flex class="pb-[12px]">
          <n-select
            :value="resource"
            :placeholder="t('panel.selectResource')"
            :options="resourcesList"
            :loading="loading"
            remote
            :disabled="resourceDisabled"
            class="max-w-80%"
            @update:value="(value: string | null) => emit('update:resource', value)"
            @click="emit('fetch-resources')"
          />
          <n-button
            strong
            secondary
            type="info"
            :disabled="resourceDisabled"
            @click="emit('confirm-resource')"
          >
            {{ t("panel.confirm") }}
          </n-button>
        </n-flex>
      </n-tab-pane>
    </n-tabs>
  </n-card>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"

const props = defineProps<{
  selectedController: string | null
  selectedDeviceKey: string | null
  playCoverAddress: string
  controllerOptions: Array<{ label: string; value: string; disabled?: boolean }>
  deviceOptions: Array<{ label: string; value: string; disabled?: boolean }>
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
  (e: "connect-devices"): void
  (e: "fetch-resources"): void
  (e: "confirm-resource"): void
}>()

const { t } = useI18n()

function handleControllerUpdate(value: string | null) {
  emit("update:selectedController", value)
  if (value !== props.selectedController) {
    emit("controller-change")
  }
}
</script>
