<template>
  <div class="text-base font-medium py-2 px-3 flex items-center gap-2">
    <NIcon size="24" style="color: var(--primary-color)">
      <PlayOutline />
    </NIcon>
    {{ $t("taskConfig.preTasks.title") }}
  </div>
</template>

<script setup lang="ts">
import { NIcon } from "naive-ui"
import { PlayOutline } from "@vicons/ionicons5"
</script>
