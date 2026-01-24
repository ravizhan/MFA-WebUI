<template>
  <n-message-provider>
    <n-dialog-provider>
      <n-layout class="p-3 lg:p-5 h-[80vh]">
        <n-grid x-gap="30" cols="1 m:3" class="p-1 lg:p-2 h-full grid-container" responsive="screen">
          <n-grid-item class="h-full">
            <LeftPanel></LeftPanel>
          </n-grid-item>
          <n-grid-item class="h-full">
            <MediumPanel></MediumPanel>
          </n-grid-item>
          <n-grid-item class="h-full">
            <RightPanel></RightPanel>
          </n-grid-item>
        </n-grid>
      </n-layout>
    </n-dialog-provider>
  </n-message-provider>
</template>
<script setup lang="ts">
import LeftPanel from "../components/LeftPanel.vue"
import MediumPanel from "../components/MediumPanel.vue"
import RightPanel from "../components/RightPanel.vue"
import { onMounted } from "vue"
onMounted(() => {
  if (Notification.permission !== "granted") {
    Notification.requestPermission()
  }
})
</script>

<style scoped>
@media (min-width: 768px) {
  .grid-container {
    grid-template-rows: minmax(0, 1fr) !important;
  }
}
</style>
