<template>
  <n-layout class="px-1 pt-3 h-[85vh] xl:h-[80vh]">
    <n-grid x-gap="20" cols="1 m:3" class="px-2" responsive="screen">
      <n-grid-item>
        <PanelControlColumn />
      </n-grid-item>
      <n-grid-item>
        <PanelTaskColumn />
      </n-grid-item>
      <n-grid-item>
        <PanelStatusColumn />
      </n-grid-item>
    </n-grid>
  </n-layout>
</template>

<script setup lang="ts">
import PanelControlColumn from "@/components/panel/PanelControlColumn.vue"
import PanelStatusColumn from "@/components/panel/PanelStatusColumn.vue"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
</script>
