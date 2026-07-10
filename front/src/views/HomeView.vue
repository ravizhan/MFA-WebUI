<template>
  <div class="space-y-3 max-w-screen-xl mx-auto">
    <!-- Header stats row -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="card bg-base-100 shadow-xl">
        <div class="card-body p-2">
          <div class="stat-title text-sm opacity-70">{{ t("panel.device") }}</div>
          <div class="stat-value text-lg flex items-center gap-2">
            <div
              class="w-3 h-3 rounded-full"
              :class="indexStore.Connected ? 'bg-success' : 'bg-error'"
            />
            {{
              indexStore.Connected
                ? t("panel.connection.connected")
                : t("panel.connection.disconnected")
            }}
          </div>
        </div>
      </div>
      <div class="card bg-base-100 shadow-xl">
        <div class="card-body p-2">
          <div class="stat-title text-sm opacity-70">{{ t("panel.taskList") }}</div>
          <div class="stat-value text-lg">
            {{ selectedTaskCount }} {{ t("common.slash") }} {{ configStore.taskList.length }}
          </div>
        </div>
      </div>
      <div class="card bg-base-100 shadow-xl">
        <div class="card-body p-2">
          <div class="stat-title text-sm opacity-70">{{ t("nav.routines") }}</div>
          <div class="stat-value text-lg">
            {{ schedulerStore.enabledTasks.length }}
          </div>
        </div>
      </div>
      <div class="card bg-base-100 shadow-xl">
        <div class="card-body p-2">
          <div class="stat-title text-sm opacity-70">{{ t("settings.about.version") }}</div>
          <div class="stat-value text-lg">
            {{ settingsStore.settings.about.version || "-" }}
          </div>
        </div>
      </div>
    </div>

    <!-- Main grid -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <!-- Left: Device + Resource -->
      <div class="space-y-3">
        <!-- Device Selection Card -->
        <div class="card bg-base-100 shadow-xl">
          <div class="card-body p-2">
            <h2 class="card-title text-base">
              <Icon icon="mdi:cellphone-link" class="text-primary text-2xl" />
              {{ t("panel.device") }}
            </h2>
            <PanelConnectionTabs
              mode="device"
              :selected-controller="deviceStore.selectedController"
              :selected-device-key="deviceStore.selectedDeviceKey"
              :play-cover-address="deviceStore.playCoverAddress"
              :controller-options="deviceStore.controllerOptions"
              :device-options="deviceStore.deviceOptions"
              :device-disabled="deviceStore.isDeviceResourceLocked"
              :resource-disabled="
                !deviceStore.selectedController || deviceStore.isDeviceResourceLocked
              "
              :selected-controller-disabled="deviceStore.selectedControllerDisabled"
              :is-play-cover="deviceStore.selectedControllerCapability?.type === 'PlayCover'"
              :resource="deviceStore.resource"
              :resources-list="deviceStore.resourcesList"
              @update:selected-controller="deviceStore.selectedController = $event"
              @update:selected-device-key="deviceStore.selectedDeviceKey = $event"
              @update:play-cover-address="deviceStore.playCoverAddress = $event"
              @update:resource="deviceStore.resource = $event"
              @controller-change="deviceStore.handleControllerChange()"
              @open-devices="deviceStore.openDevices()"
              @create-device="deviceStore.createCustomDevice($event)"
            />
          </div>
        </div>

        <!-- Resource Selection Card -->
        <div class="card bg-base-100 shadow-xl">
          <div class="card-body p-2">
            <h2 class="card-title text-base">
              <Icon icon="mdi:folder-open-outline" class="text-primary text-2xl" />
              {{ t("panel.resource") }}
            </h2>
            <PanelConnectionTabs
              mode="resource"
              :selected-controller="deviceStore.selectedController"
              :selected-device-key="deviceStore.selectedDeviceKey"
              :play-cover-address="deviceStore.playCoverAddress"
              :controller-options="deviceStore.controllerOptions"
              :device-options="deviceStore.deviceOptions"
              :device-disabled="deviceStore.isDeviceResourceLocked"
              :resource-disabled="
                !deviceStore.selectedController || deviceStore.isDeviceResourceLocked
              "
              :selected-controller-disabled="deviceStore.selectedControllerDisabled"
              :is-play-cover="deviceStore.selectedControllerCapability?.type === 'PlayCover'"
              :resource="deviceStore.resource"
              :resources-list="deviceStore.resourcesList"
              @update:resource="deviceStore.resource = $event"
            />
          </div>
        </div>
      </div>

      <!-- Right: Recipe Cards + Routine Health -->
      <div class="space-y-3 lg:col-span-2">
        <div class="card bg-base-100 shadow-xl">
          <div class="card-body p-2">
            <h2 class="card-title text-base">
              <Icon icon="mdi:book-open-variant" class="text-primary text-2xl" />
              {{ t("panel.preset.title") }}
            </h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
              <HomeRecipeCard
                v-for="preset in recipeCards"
                :key="preset.name"
                :preset="preset"
                @apply="applyPreset"
              />
            </div>
          </div>
        </div>

        <!-- Routine Health -->
        <div class="card bg-base-100 shadow-xl">
          <div class="card-body p-2">
            <h2 class="card-title text-base">
              <Icon icon="mdi:heart-pulse" class="text-primary text-2xl" />
              {{ t("nav.routines") }}
            </h2>
            <RoutineHealthCard />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { Icon } from "@iconify/vue"
import HomeRecipeCard from "@/components/home/HomeRecipeCard.vue"
import RoutineHealthCard from "@/components/home/RoutineHealthCard.vue"
import PanelConnectionTabs from "@/components/panel/PanelConnectionTabs.vue"
import {
  useIndexStore,
  useInterfaceStore,
  useTaskConfigStore,
  useSchedulerStore,
  useSettingsStore,
  useDeviceConnectionStore,
} from "@/stores"
import { resolveInterfaceText } from "@/utils/interface/content"

const { t, locale } = useI18n()
const router = useRouter()
const indexStore = useIndexStore()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const schedulerStore = useSchedulerStore()
const settingsStore = useSettingsStore()
const deviceStore = useDeviceConnectionStore()

const selectedTaskCount = computed(() => configStore.taskList.filter((task) => task.checked).length)

const recipeCards = computed(() => {
  return interfaceStore.getPresetList.map((preset) => {
    const taskCount = preset.task?.filter((t) => t.enabled !== false).length || 0
    return {
      name: preset.name,
      label: resolveInterfaceText(
        interfaceStore.interface,
        locale.value,
        preset.label,
        preset.name,
      ),
      description: preset.description || t("panel.preset.noDescription"),
      taskCount,
    }
  })
})

function applyPreset(name: string) {
  configStore.selectPreset(name)
  router.push({ name: "tasks" })
}

onMounted(() => {
  deviceStore.init()
})

onUnmounted(() => {
  deviceStore.cleanup()
})
</script>
