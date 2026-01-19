<template>
  <n-config-provider :theme="naiveTheme">
    <n-message-provider>
      <n-dialog-provider>
        <div class="lg:pt-10 lg:pb-10 pt-0 pb-0">
          <n-layout class="lg:shadow-3xl lg:w-[80vw] w-full m-auto m-0 pt-0">
            <n-layout-header bordered>
              <div class="text-align-center mt-3 text-2xl">{{ name }}</div>
              <n-menu mode="horizontal" class="justify-between" :options="menuOptions" />
            </n-layout-header>
            <n-layout>
              <router-view></router-view>
            </n-layout>
            <n-layout-footer bordered class="text-align-center">
              <a href="https://github.com/ravizhan/MFA-WebUI" target="_blank">
                Powered by MFA-WebUI
              </a>
            </n-layout-footer>
          </n-layout>
        </div>
      </n-dialog-provider>
    </n-message-provider>
    <n-global-style />
  </n-config-provider>
</template>

<script setup lang="ts">
import { NIcon } from "naive-ui"
import { h, ref, onMounted, watch, computed, watchEffect } from "vue"
import { RouterLink } from "vue-router"
import { useInterfaceStore } from "./stores/interface.ts"
import { useUserConfigStore } from "./stores/userConfig.ts"
import { useSettingsStore } from "./stores/settings"
import { darkTheme } from "naive-ui"

import githubMarkdownAutoUrl from "github-markdown-css/github-markdown.css?url"
import githubMarkdownLightUrl from "github-markdown-css/github-markdown-light.css?url"
import githubMarkdownDarkUrl from "github-markdown-css/github-markdown-dark.css?url"

function renderIcon(icon: string) {
  return () => h(NIcon, null, { default: () => h("div", { class: icon }) })
}
const interfaceStore = useInterfaceStore()
const configStore = useUserConfigStore()
const settingsStore = useSettingsStore()
const name = computed(() => interfaceStore.interface?.name || "")
const offset = ref(0)
const screenWidth = ref(window.innerWidth)

const naiveTheme = computed(() => (settingsStore.isDarkMode ? darkTheme : null))

const markdownCssHref = computed(() => {
  const mode = settingsStore.settings.ui.darkMode
  if (mode === "auto") return githubMarkdownAutoUrl
  return mode ? githubMarkdownDarkUrl : githubMarkdownLightUrl
})

function ensureMarkdownStylesheet(href: string) {
  const id = "github-markdown-theme"
  let el = document.getElementById(id) as HTMLLinkElement | null
  if (!el) {
    el = document.createElement("link")
    el.id = id
    el.rel = "stylesheet"
    document.head.appendChild(el)
  }
  if (el.href !== href) {
    el.href = href
  }
}
const handleResize = () => {
  screenWidth.value = window.innerWidth
}
onMounted(async () => {
  settingsStore.initSystemThemeListener()
  await interfaceStore.setInterface()
  await configStore.loadConfig()
  if (!settingsStore.initialized) {
    settingsStore.fetchSettings()
  }

  window.addEventListener("resize", handleResize)
})

watchEffect(() => {
  ensureMarkdownStylesheet(markdownCssHref.value)
})
watch(screenWidth, (newValue) => {
  if (newValue < 450) {
    offset.value = 0
  } else if (newValue >= 450 && newValue < 600) {
    offset.value = 1
  } else {
    offset.value = 3
  }
})

const menuOptions = [
  {
    label: () =>
      h(
        RouterLink,
        {
          to: {
            name: "panel",
          },
        },
        { default: () => "首页" },
      ),
    key: "panel",
    icon: renderIcon("i-mdi-home"),
  },
  {
    label: () =>
      h(
        RouterLink,
        {
          to: {
            name: "setting",
          },
        },
        { default: () => "设置" },
      ),
    key: "setting",
    icon: renderIcon("i-mdi-cog"),
  },
]
</script>
