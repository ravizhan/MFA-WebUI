<template>
  <div class="min-h-screen bg-base-200 transition-colors duration-300 overflow-x-hidden">
    <!-- Navbar -->
    <div class="navbar bg-base-100 shadow-lg sticky top-0 z-40 px-4">
      <div class="navbar-start">
        <span class="text-xl font-bold tracking-wide text-primary">{{ name }}</span>
      </div>
      <div class="navbar-center hidden lg:flex">
        <ul class="menu menu-horizontal px-1 gap-1">
          <li v-for="item in navItems" :key="item.key">
            <RouterLink
              :to="item.to"
              :class="{
                active: route.name === item.key,
                'bg-primary text-primary-content': route.name === item.key,
              }"
              class="rounded-lg"
            >
              <Icon :icon="item.icon" class="text-lg" />
              {{ item.label }}
            </RouterLink>
          </li>
        </ul>
      </div>
      <div class="navbar-end gap-2">
        <!-- Dark mode toggle -->
        <button
          class="btn btn-ghost btn-circle btn-sm tooltip"
          :data-tip="settingsStore.isDarkMode ? t('common.lightMode') : t('common.darkMode')"
          @click="toggleDarkMode"
        >
          <Icon
            :icon="settingsStore.isDarkMode ? 'mdi:weather-sunny' : 'mdi:weather-night'"
            class="text-base"
          />
        </button>
      </div>
    </div>

    <!-- Main content -->
    <main class="pb-24 lg:pb-4 transition-all duration-300 overflow-x-hidden">
      <div class="w-full mx-auto px-3 py-4">
        <router-view v-slot="{ Component, route: r }">
          <transition
            :name="typeof r.meta.transition === 'string' ? r.meta.transition : 'fade'"
            mode="out-in"
          >
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>

    <!-- Dock nav (mobile) -->
    <div
      class="lg:hidden fixed bottom-4 left-1/2 -translate-x-1/2 bg-base-100/90 backdrop-blur shadow-2xl rounded-2xl z-40 px-2 py-2 flex items-center gap-1"
      style="padding-bottom: calc(0.5rem + env(safe-area-inset-bottom))"
    >
      <button
        v-for="item in navItems"
        :key="item.key"
        class="flex flex-col items-center justify-center gap-0.5 px-3 py-1.5 rounded-xl transition-colors min-w-[3.5rem]"
        :class="
          route.name === item.key
            ? 'bg-primary text-primary-content'
            : 'text-base-content/70 hover:bg-base-200'
        "
        @click="$router.push(item.to)"
      >
        <Icon :icon="item.icon" class="text-xl" />
        <span class="text-[10px] truncate">{{ item.label }}</span>
      </button>
    </div>

    <!-- Toast container -->
    <div class="toast toast-top toast-end z-50">
      <div v-for="toast in toasts" :key="toast.id" :class="['alert', toastClass(toast.type)]">
        <Icon
          :icon="
            toast.type === 'success'
              ? 'mdi:check-circle'
              : toast.type === 'error'
                ? 'mdi:alert-circle'
                : toast.type === 'warning'
                  ? 'mdi:alert'
                  : 'mdi:information'
          "
          class="text-lg"
        />
        <span>{{ toast.content }}</span>
      </div>
    </div>

    <!-- Update dialog -->
    <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch, watchEffect } from "vue"
import { useRoute } from "vue-router"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import markdownAutoHref from "github-markdown-css/github-markdown.css?url"
import markdownDarkHref from "github-markdown-css/github-markdown-dark.css?url"
import markdownLightHref from "github-markdown-css/github-markdown-light.css?url"
import UpdateDialog from "@/components/settings/dialogs/UpdateDialog.vue"
import { checkUpdateApi, type UpdateInfo } from "@/services/api"
import { useToasts } from "@/services/feedback/message"
import { useInterfaceStore, useSettingsStore, useTaskConfigStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"

const { t } = useI18n()
const route = useRoute()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const settingsStore = useSettingsStore()
const name = computed(() => interfaceStore.interface?.name || "MWU")

const toasts = useToasts()

function toastClass(type: string): string {
  switch (type) {
    case "success":
      return "alert-success"
    case "error":
      return "alert-error"
    case "warning":
      return "alert-warning"
    default:
      return "alert-info"
  }
}

const navItems = computed(() => [
  { key: "home", label: t("nav.home"), icon: "mdi:home", to: { name: "home" } },
  { key: "tasks", label: t("nav.tasks"), icon: "mdi:format-list-checks", to: { name: "tasks" } },
  { key: "logs", label: t("nav.logs"), icon: "mdi:file-document-outline", to: { name: "logs" } },
  {
    key: "routines",
    label: t("nav.routines"),
    icon: "mdi:clock-outline",
    to: { name: "routines" },
  },
  { key: "settings", label: t("nav.settings"), icon: "mdi:cog", to: { name: "settings" } },
])

function toggleDarkMode() {
  const newValue = !settingsStore.isDarkMode
  void settingsStore.updateSetting("ui", "darkMode", newValue)
}

const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

function ensureMarkdownStylesheet(href: string) {
  const id = "github-markdown-theme"
  let el = document.getElementById(id)
  if (!(el instanceof HTMLLinkElement)) {
    el = document.createElement("link")
    el.id = id
    el.rel = "stylesheet"
    document.head.appendChild(el)
  }
  if (el.href !== href) {
    el.href = href
  }
}

const checkForUpdatesOnLoad = async () => {
  if (sessionStorage.getItem("mwu-update-checked")) {
    return
  }

  if (!settingsStore.settings.update || !settingsStore.settings.update.autoUpdate) {
    return
  }

  const [result, err] = await tryCatch(() => checkUpdateApi())
  if (err) {
    console.error("Failed to check for updates on load:", err)
    return
  }
  sessionStorage.setItem("mwu-update-checked", "true")
  if (result.status === "success" && result.update_info?.is_update_available) {
    updateInfo.value = result.update_info
    showUpdateDialog.value = true
  }
}

onMounted(async () => {
  settingsStore.initSystemThemeListener()
  await interfaceStore.setInterface()
  await configStore.loadConfig()
  if (!settingsStore.initialized) {
    await settingsStore.fetchSettings()
  }

  void checkForUpdatesOnLoad()
})

watch(
  () => settingsStore.isDarkMode,
  (isDark) => {
    document.documentElement.setAttribute("data-theme", isDark ? "mwu-dark" : "mwu-light")
  },
  { immediate: true },
)

function markdownHref(mode: boolean | "auto"): string {
  if (mode === "auto") {
    return markdownAutoHref
  }
  if (mode) {
    return markdownDarkHref
  }
  return markdownLightHref
}

watchEffect(() => {
  const mode = settingsStore.settings.ui.darkMode
  ensureMarkdownStylesheet(markdownHref(mode))
})
</script>
