<template>
  <div class="col-name">任务设置</div>
  <n-card hoverable>114514</n-card>
  <div class="col-name">任务说明</div>
  <n-card hoverable>1919810</n-card>
</template>
<script setup lang="ts">
import { watch } from 'vue'
// import { useInterfaceStore } from '../stores/interface.ts'
import { useIndexStore } from '../stores'

// const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()

watch(
  () => indexStore.SelectedTaskID,
  (newList) => {
    console.log(newList)
  },
  { immediate: true },
)
</script>
