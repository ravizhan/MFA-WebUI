<template>
  <n-card content-style="padding: 0;">
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" tab="设备连接">
        <div class="select-border">
          <div style="display: flex; align-items: center; gap: 8px">
            <n-select
              v-model:value="model.device"
              placeholder="请选择一个设备"
              :options="devices_list"
              :loading="loading"
              remote
              @click="get_device"
              style="flex: 1"
            />
            <n-button strong secondary type="info" @click="connectDevices">连接</n-button>
          </div>
        </div>
      </n-tab-pane>
      <n-tab-pane name="resource" tab="资源选择">
        <div class="select-border">
          <div style="display: flex; align-items: center; gap: 8px">
            <n-select
              v-model:value="model.device"
              placeholder="请选择一个资源"
              :options="devices_list"
              :loading="loading"
              remote
              @click="get_resource"
              style="flex: 1"
            />
            <n-button strong secondary type="info" @click="post_resource">确定</n-button>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>
  </n-card>
  <div class="col-name">任务列表</div>
  <n-card hoverable>
    <n-list>
      <VueDraggable v-model="task_list">
        <n-list-item v-for="item in task_list" :key="item.id">
          <n-checkbox size="large" :label="item.name" />
        </n-list-item>
      </VueDraggable>
    </n-list>
    <n-flex class="form-btn" justify="center">
      <n-button strong secondary type="info" size="large" @click="startTask"> 开始任务</n-button>
      <n-button strong secondary type="info" size="large" @click="stopTask"> 中止任务</n-button>
    </n-flex>
  </n-card>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import { getDevices } from '@/assets/api'
import { VueDraggable } from 'vue-draggable-plus'
import { useMessage } from 'naive-ui'
const message = useMessage()

const task_list = ref(null)
task_list.value = ['1', '2', '3', '4'].map((name, index) => {
  return { name, order: index + 1 }
})

const model = ref({
  device: null,
  api_key: '',
  endpoint: '',
})
const devices_list = ref([])
const loading = ref(false)

function get_device() {
  getDevices().then((data) => {
    if (data['status'] === 'failed') {
      message.error(data['message'])
      loading.value = true
      return
    }
    const devices_data = data['devices']
    for (let device of devices_data) {
      console.log(devices_data)
      devices_list.value.push({
        label: device['name'] + ' ' + device['address'],
        value: device,
      })
    }
    loading.value = false
  })
}

function get_resource() {
  //TODO
}

function post_resource() {
  //TODO
}

onMounted(() => {
  //TODO
})
</script>
<style scoped>
.list-group-item i {
  cursor: pointer;
}
.select-border {
  padding: 0 12px 12px 12px;
}
</style>
