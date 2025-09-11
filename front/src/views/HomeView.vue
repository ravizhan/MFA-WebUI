<template>
  <n-message-provider>
    <n-dialog-provider>
      <n-layout class="m-3 lg:m-5">
        <n-grid x-gap="36" cols="1 m:3" class="p-1 lg:p-2" responsive="screen">
          <n-grid-item>
            <left></left>
          </n-grid-item>
          <n-grid-item>
            <medium></medium>
          </n-grid-item>
          <n-grid-item>
            <right></right>
          </n-grid-item>
        </n-grid>
      </n-layout>
    </n-dialog-provider>
  </n-message-provider>
</template>
<script setup lang="ts">
import left from '../components/left.vue'
import medium from '../components/medium.vue'
import right from '../components/right.vue'
import { onMounted } from 'vue'
onMounted(() => {
  if (Notification.permission !== 'granted') {
    Notification.requestPermission()
  }
})
</script>
