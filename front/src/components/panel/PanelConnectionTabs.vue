<template>
  <!-- Device-only mode: no tabs, no card wrapper -->
  <div v-if="mode === 'device'" class="flex flex-wrap gap-2">
    <select
      :value="selectedController"
      class="select select-bordered select-sm flex-1 min-w-[8rem]"
      :disabled="deviceDisabled"
      @change="handleControllerUpdate(($event.target as HTMLSelectElement).value)"
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
      @input="emit('update:playCoverAddress', ($event.target as HTMLInputElement).value)"
    />
    <SearchableSelect
      v-else
      :model-value="selectedDeviceKey"
      :options="flatDeviceOptions"
      :placeholder="t('panel.selectDevice')"
      :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
      class="flex-1 min-w-[10rem]"
      @update:model-value="emit('update:selectedDeviceKey', $event)"
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
      @change="emit('update:resource', ($event.target as HTMLSelectElement).value || null)"
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
            @change="handleControllerUpdate(($event.target as HTMLSelectElement).value)"
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
            @input="emit('update:playCoverAddress', ($event.target as HTMLInputElement).value)"
          />
          <SearchableSelect
            v-else
            :model-value="selectedDeviceKey"
            :options="flatDeviceOptions"
            :placeholder="t('panel.selectDevice')"
            :disabled="!selectedController || selectedControllerDisabled || deviceDisabled"
            class="flex-1 min-w-[10rem]"
            @update:model-value="emit('update:selectedDeviceKey', $event)"
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
            @change="emit('update:resource', ($event.target as HTMLSelectElement).value || null)"
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

const props = withDefaults(
  defineProps<{
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
    loading: boolean
    deviceDisabled: boolean
    resourceDisabled: boolean
    selectedControllerDisabled: boolean
    isPlayCover: boolean
    resource: string | null
    resourcesList: Array<{ label: string; value: string }>
    mode?: "device" | "resource" | "tabs"
  }>(),
  { mode: "tabs" },
)

const emit = defineEmits<{
  (e: "update:selectedController", value: string | null): void
  (e: "update:selectedDeviceKey", value: string | null): void
  (e: "update:playCoverAddress", value: string): void
  (e: "update:resource", value: string | null): void
  (e: "controller-change"): void
  (e: "refresh-devices"): void
}>()

const { t } = useI18n()
const activeTab = ref<"device" | "resource">("device")

const deviceOptionGroups = computed(() => {
  const groups: Array<{
    label: string
    key: string
    children: Array<{ label: string; value: string }>
  }> = []
  let currentGroup: (typeof groups)[0] | null = null
  for (const opt of props.deviceOptions) {
    if (opt.type === "group" && opt.children) {
      groups.push({ label: opt.label, key: opt.key || opt.label, children: opt.children })
    } else if (opt.type === "group" && !opt.children) {
      currentGroup = { label: opt.label, key: opt.key || opt.label, children: [] }
      groups.push(currentGroup)
    } else if (currentGroup && opt.value !== undefined) {
      currentGroup.children.push({ label: opt.label, value: opt.value })
    } else if (opt.value !== undefined) {
      // Flat option without group
      if (groups.length === 0 || groups[groups.length - 1].key !== "default") {
        groups.push({ label: "", key: "default", children: [] })
      }
      groups[groups.length - 1].children.push({ label: opt.label, value: opt.value })
    }
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
  emit("update:selectedController", value)
  if (value !== props.selectedController) {
    emit("controller-change")
  }
}
</script>
