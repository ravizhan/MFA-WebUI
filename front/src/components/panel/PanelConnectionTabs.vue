<template>
  <!-- Device-only mode: no tabs, no card wrapper -->
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
    <SearchableSelect
      v-else
      :model-value="selectedDeviceKey"
      :options="flatDeviceOptions"
      :placeholder="t('panel.selectDevice')"
      :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
      class="flex-1 min-w-[10rem]"
      @update:model-value="emit('update:selected-device-key', $event)"
    />
    <button
      class="btn btn-outline btn-sm"
      :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
      @click="emit('refresh-devices')"
    >
      {{ t("panel.refresh") }}
    </button>
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
          <SearchableSelect
            v-else
            :model-value="selectedDeviceKey"
            :options="flatDeviceOptions"
            :placeholder="t('panel.selectDevice')"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            class="flex-1 min-w-[10rem]"
            @update:model-value="emit('update:selected-device-key', $event)"
          />
          <button
            class="btn btn-outline btn-sm"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            @click="emit('refresh-devices')"
          >
            {{ t("panel.refresh") }}
          </button>
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
import { ref, computed } from "vue"
import { useI18n } from "vue-i18n"
import SearchableSelect from "@/components/common/SearchableSelect.vue"

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
  deviceOptions: Array<{
    label: string
    value: string
    type?: string
    key?: string
    children?: Array<{ label: string; value: string }>
  }>
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
  (e: "refresh-devices"): void
}>()

const { t } = useI18n()
const activeTab = ref<"device" | "resource">("device")

type DeviceOptionGroup = {
  label: string
  key: string
  children: Array<{ label: string; value: string }>
}

function pushGroup(
  groups: DeviceOptionGroup[],
  label: string,
  key: string,
  children: Array<{ label: string; value: string }> = [],
): DeviceOptionGroup {
  const group: DeviceOptionGroup = { label, key, children }
  groups.push(group)
  return group
}

function ensureDefaultGroup(groups: DeviceOptionGroup[]): DeviceOptionGroup {
  const last = groups[groups.length - 1]
  if (last && last.key === "default") return last
  return pushGroup(groups, "", "default")
}

const deviceOptionGroups = computed(() => {
  const groups: DeviceOptionGroup[] = []
  let currentGroup: DeviceOptionGroup | null = null
  for (const opt of deviceOptions) {
    if (opt.type === "group") {
      currentGroup = opt.children
        ? pushGroup(groups, opt.label, opt.key || opt.label, opt.children)
        : pushGroup(groups, opt.label, opt.key || opt.label)
      continue
    }
    if (opt.value === undefined) continue
    if (currentGroup) {
      currentGroup.children.push({ label: opt.label, value: opt.value })
      continue
    }
    ensureDefaultGroup(groups).children.push({ label: opt.label, value: opt.value })
  }
  return groups
})

const flatDeviceOptions = computed(() => {
  const options: Array<{ label: string; value: string }> = []
  for (const group of deviceOptionGroups.value) {
    for (const child of group.children) {
      options.push({
        label: group.label ? `${group.label} · ${child.label}` : child.label,
        value: child.value,
      })
    }
  }
  return options
})

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
