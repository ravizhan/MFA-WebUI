<template>
  <n-card
    v-if="compactView"
    hoverable
    class="preset-mobile-card"
    content-style="padding: 0.875rem;"
  >
    <n-space vertical size="medium" class="preset-mobile-content">
      <n-empty v-if="presets.length === 0" :description="t('panel.preset.empty')" />

      <template v-else>
        <div class="preset-mobile-select-row">
          <span class="preset-mobile-select-label">{{ t("panel.preset.title") }}</span>
          <n-select
            class="preset-mobile-select"
            :value="currentPresetValue"
            :options="presetOptions"
            @update:value="handlePresetChange"
          />
        </div>

        <template v-if="activePreset">
          <MarkdownViewer
            :source="descriptionContent"
            :empty-text="t('panel.preset.noDescription')"
            body-class="preset-mobile-markdown"
          />
        </template>

        <n-empty v-else :description="t('panel.preset.customDescription')" />
      </template>
    </n-space>
  </n-card>

  <n-card v-else hoverable class="preset-desktop-card" content-style="padding: 0.5rem 1rem;">
    <n-collapse
      v-model:expanded-names="desktopExpandedNames"
      arrow-placement="right"
      class="preset-desktop-collapse"
    >
      <n-collapse-item name="preset" :title="desktopCollapseTitle" display-directive="show">
        <n-space vertical size="medium" class="preset-desktop-content">
          <n-empty v-if="presets.length === 0" :description="t('panel.preset.empty')" />

          <template v-else>
            <div class="desktop-tabs-row">
              <n-button
                circle
                tertiary
                size="small"
                class="tabs-scroll-button"
                :disabled="!canScrollLeft"
                @click="scrollTabs(-1)"
              >
                <template #icon>
                  <n-icon><div class="i-mdi-chevron-left"></div></n-icon>
                </template>
              </n-button>

              <div ref="desktopTabsHost" class="desktop-tabs-host">
                <n-tabs
                  type="line"
                  animated
                  :value="currentPresetValue"
                  @update:value="handlePresetChange"
                >
                  <n-tab-pane :name="CUSTOM_PRESET_NAME">
                    <template #tab>{{ t("panel.preset.custom") }}</template>
                  </n-tab-pane>
                  <n-tab-pane v-for="preset in presets" :key="preset.name" :name="preset.name">
                    <template #tab>{{ resolvePresetLabel(preset.label, preset.name) }}</template>
                  </n-tab-pane>
                </n-tabs>
              </div>

              <n-button
                circle
                tertiary
                size="small"
                class="tabs-scroll-button"
                :disabled="!canScrollRight"
                @click="scrollTabs(1)"
              >
                <template #icon>
                  <n-icon><div class="i-mdi-chevron-right"></div></n-icon>
                </template>
              </n-button>
            </div>

            <template v-if="activePreset">
              <MarkdownViewer
                :source="descriptionContent"
                :empty-text="t('panel.preset.noDescription')"
                body-class="preset-desktop-markdown"
              />
            </template>

            <n-empty v-else :description="t('panel.preset.customDescription')" />
          </template>
        </n-space>
      </n-collapse-item>
    </n-collapse>
  </n-card>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import MarkdownViewer from "@/components/panel/common/MarkdownViewer.vue"
import { useIndexStore, useInterfaceStore, useTaskConfigStore } from "@/stores"
import { CUSTOM_PRESET_NAME } from "@/types/task-config/model"
import { resolveInterfaceDocumentContent, resolveInterfaceText } from "@/utils/interface/content"
import { useViewport } from "@/utils/viewport/useViewport"

const presetCollapseName = "preset"

const { isMobile: compactView } = useViewport()
const descriptionContent = ref("")
const desktopExpandedNames = ref<Array<string | number>>([])
const desktopTabsHost = ref<HTMLElement | null>(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)
const { t, locale } = useI18n()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const indexStore = useIndexStore()
let desktopTabsScrollEl: HTMLElement | null = null

const presets = computed(() => interfaceStore.getPresetList)
const currentPresetValue = computed(() => configStore.selectedPresetName)
const activePreset = computed(() =>
  configStore.selectedPresetName !== CUSTOM_PRESET_NAME
    ? interfaceStore.getPresetByName(configStore.selectedPresetName)
    : null,
)
const activePresetLabel = computed(() =>
  activePreset.value
    ? resolvePresetLabel(activePreset.value.label, activePreset.value.name)
    : t("panel.preset.custom"),
)
const presetOptions = computed(() => [
  {
    label: t("panel.preset.custom"),
    value: CUSTOM_PRESET_NAME,
  },
  ...presets.value.map((preset) => ({
    label: resolvePresetLabel(preset.label, preset.name),
    value: preset.name,
  })),
])
const desktopCollapseTitle = computed(() => {
  if (presets.value.length === 0) {
    return t("panel.preset.title")
  }
  return `${t("panel.preset.title")}(${activePresetLabel.value})`
})

function resolvePresetLabel(label: string | undefined, fallback: string) {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

function selectFirstRelevantTask() {
  const firstCheckedTask = configStore.taskList.find((task) => task.checked)
  const targetTask = firstCheckedTask || configStore.taskList[0]
  if (targetTask) {
    indexStore.SelectTask(targetTask.id)
  }
}

function handlePresetChange(value: string) {
  if (configStore.selectPreset(value)) {
    selectFirstRelevantTask()
  }
}

function getDesktopTabsScrollEl() {
  const host = desktopTabsHost.value
  if (!host) {
    return null
  }

  const wrapper = host.querySelector(".n-tabs-nav-scroll-wrapper") as HTMLElement | null
  if (!wrapper) {
    return null
  }

  const scrollEl = wrapper.querySelector(".v-x-scroll") as HTMLElement | null
  if (scrollEl) {
    return scrollEl
  }

  return wrapper.firstElementChild instanceof HTMLElement ? wrapper.firstElementChild : null
}

function updateDesktopTabScrollState() {
  const scrollEl = getDesktopTabsScrollEl()
  if (!scrollEl) {
    canScrollLeft.value = false
    canScrollRight.value = false
    return
  }

  canScrollLeft.value = scrollEl.scrollLeft > 4
  canScrollRight.value = scrollEl.scrollLeft + scrollEl.clientWidth < scrollEl.scrollWidth - 4
}

function detachDesktopTabsScrollListener() {
  if (!desktopTabsScrollEl) {
    return
  }

  desktopTabsScrollEl.removeEventListener("scroll", updateDesktopTabScrollState)
  desktopTabsScrollEl = null
}

async function syncDesktopTabsScroll() {
  await nextTick()
  detachDesktopTabsScrollListener()

  if (compactView.value || !desktopExpandedNames.value.includes(presetCollapseName)) {
    updateDesktopTabScrollState()
    return
  }

  const scrollEl = getDesktopTabsScrollEl()
  if (!scrollEl) {
    updateDesktopTabScrollState()
    return
  }

  desktopTabsScrollEl = scrollEl
  desktopTabsScrollEl.addEventListener("scroll", updateDesktopTabScrollState, { passive: true })
  updateDesktopTabScrollState()
}

function scrollTabs(direction: -1 | 1) {
  const scrollEl = getDesktopTabsScrollEl()
  if (!scrollEl) {
    return
  }

  const distance = Math.max(Math.round(scrollEl.clientWidth * 0.6), 160)
  scrollEl.scrollBy({ left: direction * distance, behavior: "smooth" })
}

watch(
  [activePreset, () => interfaceStore.interface],
  async ([preset]) => {
    descriptionContent.value = preset
      ? await resolveInterfaceDocumentContent(interfaceStore.interface, "", preset.description)
      : ""
  },
  { immediate: true },
)

watch(
  [
    compactView,
    currentPresetValue,
    () => presets.value.length,
    () => locale.value,
    desktopExpandedNames,
  ],
  () => {
    void syncDesktopTabsScroll()
  },
  { immediate: true },
)

onUnmounted(() => {
  detachDesktopTabsScrollListener()
})
</script>

<style scoped>
.preset-mobile-card {
  margin: 1rem 0;
}

.preset-mobile-content {
  gap: 0.875rem;
}

.preset-mobile-select-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.preset-mobile-select-label {
  flex: none;
  font-weight: 600;
  white-space: nowrap;
}

.preset-mobile-select {
  min-width: 0;
  flex: 1;
}

.preset-mobile-markdown {
  min-height: 5rem;
  max-height: 12rem;
}

.preset-desktop-card {
  margin: 1rem 0;
  overflow: hidden;
}

.preset-desktop-content {
  padding-top: 0.25rem;
  padding-bottom: 0.25rem;
}

.desktop-tabs-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0 0.25rem 0.5rem;
}

.desktop-tabs-host {
  min-width: 0;
  flex: 1;
}

.tabs-scroll-button {
  flex: none;
}

.preset-desktop-markdown {
  min-height: 5rem;
  max-height: 12rem;
}

.desktop-tabs-host :deep(.n-tabs-nav-scroll-wrapper) {
  overflow: hidden;
}

.preset-desktop-collapse :deep(.n-collapse-item) {
  margin-left: 0;
  border-top: none;
}

.preset-desktop-collapse :deep(.n-collapse-item:first-child > .n-collapse-item__header) {
  padding-top: 0.875rem !important;
}

.preset-desktop-collapse :deep(.n-collapse-item__header) {
  min-height: 3.25rem;
  padding: 0.875rem 0.25rem;
  align-items: center;
}

.preset-desktop-collapse :deep(.n-collapse-item__content-wrapper) {
  overflow: hidden;
}

.preset-desktop-collapse :deep(.n-collapse-item__content-inner) {
  padding-top: 0rem !important;
  padding-bottom: 0.5rem;
}

:deep(.n-collapse-item__header-main) {
  justify-content: space-between;
}
</style>
