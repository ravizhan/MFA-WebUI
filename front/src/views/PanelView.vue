<template>
  <n-message-provider>
    <n-dialog-provider>
      <n-layout class="m-3 lg:m-5">
        <n-grid x-gap="36" cols="1 m:3" class="p-1 lg:p-2" responsive="screen">
          <n-grid-item>
            <LeftPanel></LeftPanel>
          </n-grid-item>
          <n-grid-item>
            <MediumPanel></MediumPanel>
          </n-grid-item>
          <n-grid-item>
            <RightPanel></RightPanel>
          </n-grid-item>
        </n-grid>
      </n-layout>
    </n-dialog-provider>
  </n-message-provider>
</template>
<script setup lang="ts">
import LeftPanel from '../components/LeftPanel.vue'
import MediumPanel from '../components/MediumPanel.vue'
import RightPanel from '../components/RightPanel.vue'
import { onMounted } from 'vue'
onMounted(() => {
  if (Notification.permission !== 'granted') {
    Notification.requestPermission()
  }
})
</script>
