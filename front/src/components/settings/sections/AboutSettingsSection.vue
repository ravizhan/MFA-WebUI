<template>
  <div class="space-y-4">
    <div class="overflow-x-auto">
      <NDataTable
        :columns="columns"
        :data="rows"
        size="small"
        :bordered="false"
        :single-line="false"
      />
    </div>

    <NDivider />

    <NButton type="warning" size="small" @click="handleResetSettings">
      {{ t("settings.about.reset") }}
    </NButton>
  </div>
</template>

<script setup lang="ts">
import { computed, h, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { NButton, NDataTable, NDivider, NIcon } from "naive-ui"
import type { DataTableColumns } from "naive-ui"
import { BugOutline, LogoGithub } from "@vicons/ionicons5"
import { showGlobalMessage } from "@/services/feedback/message"
import { useSettingsStore } from "@/stores"

interface AboutRow {
  label: string
  value: string
  href?: string
  icon?: Component
}

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

const rows = computed<AboutRow[]>(() => {
  const about = settings.value.about
  const result: AboutRow[] = [
    {
      label: t("settings.about.version"),
      value: about.version || t("common.unknown"),
    },
    {
      label: t("settings.about.author"),
      value: about.author || t("common.unknown"),
      href: about.author ? `https://github.com/${about.author}` : undefined,
      icon: LogoGithub,
    },
    {
      label: t("settings.about.license"),
      value: about.license || "MIT",
    },
    {
      label: t("settings.about.homepage"),
      value: about.github || "https://github.com/ravizhan/MWU",
      href: about.github || "https://github.com/ravizhan/MWU",
      icon: LogoGithub,
    },
    {
      label: t("settings.about.issue"),
      value: t("settings.about.githubIssues"),
      href: about.issueUrl || "https://github.com/ravizhan/MWU/issues",
      icon: BugOutline,
    },
  ]

  if (about.contact) {
    result.push({
      label: t("settings.about.contact"),
      value: about.contact,
    })
  }

  result.push({
    label: t("settings.about.description"),
    value: about.description || t("settings.about.defaultDescription"),
  })

  return result
})

const columns = computed<DataTableColumns<AboutRow>>(() => [
  {
    key: "label",
    title: "",
    width: 140,
    render: (row) => h("span", { class: "font-medium" }, row.label),
  },
  {
    key: "value",
    title: "",
    render: (row) => {
      if (!row.href) {
        return row.value
      }

      return h(
        NButton,
        {
          text: true,
          type: "primary",
          tag: "a",
          href: row.href,
          target: "_blank",
          rel: "noopener noreferrer",
        },
        {
          icon: () => h(NIcon, { size: 18 }, { default: () => h(row.icon ?? LogoGithub) }),
          default: () => row.value,
        },
      )
    },
  },
])

function handleResetSettings() {
  if (confirm(t("settings.about.resetConfirm"))) {
    void settingsStore.resetSettings().then((success) => {
      if (success) {
        showGlobalMessage("success", t("settings.about.resetSuccess"))
      }
    })
  }
}
</script>
