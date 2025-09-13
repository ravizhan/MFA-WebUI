<template>
  <n-card content-style="padding: 0;" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" tab="设备连接">
        <n-flex class="px-[12px] pb-[12px]">
          <n-select
            v-model:value="device"
            placeholder="请选择一个设备"
            :options="devices_list"
            :loading="loading"
            remote
            @click="get_device"
            class="max-w-80%"
          />
          <n-button strong secondary type="info" @click="connectDevices">连接</n-button>
        </n-flex>
      </n-tab-pane>
      <n-tab-pane name="resource" tab="资源选择">
        <n-flex class="px-[12px] pb-[12px]">
          <n-select
            v-model:value="resource"
            placeholder="请选择一个资源"
            :options="devices_list"
            :loading="loading"
            remote
            @click="get_resource"
            class="max-w-80%"
          />
          <n-button strong secondary type="info" @click="post_resource">确定</n-button>
        </n-flex>
      </n-tab-pane>
    </n-tabs>
  </n-card>
  <div class="col-name">任务列表</div>
  <n-card hoverable>
    <n-list hoverable bordered>
      <template v-if="scroll_show">
        <n-scrollbar class="max-h-80">
          <VueDraggable v-model="task_list">
            <n-list-item v-for="item in task_list" :key="item.id">
              <n-checkbox size="large" :label="item.name" />
              <template #suffix>
                <n-button quaternary circle @click="indexStore.SelectTask(item.id)">
                  <template #icon>
                    <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                  </template>
                </n-button>
              </template>
            </n-list-item>
          </VueDraggable>
        </n-scrollbar>
      </template>
      <template v-else>
        <VueDraggable v-model="task_list">
          <n-list-item v-for="item in task_list" :key="item.id">
            <n-checkbox size="large" :label="item.name" v-model:checked="item.checked" />
            <template #suffix>
              <n-button quaternary circle @click="indexStore.SelectTask(item.id)">
                <template #icon>
                  <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                </template>
              </n-button>
            </template>
          </n-list-item>
        </VueDraggable>
      </template>
    </n-list>
    <n-flex class="form-btn" justify="center">
      <n-button strong secondary type="info" size="large" @click="startTask"> 开始任务</n-button>
      <n-button strong secondary type="info" size="large" @click="stopTask"> 中止任务</n-button>
    </n-flex>
  </n-card>
</template>
<script setup lang="ts">
import { watch, ref } from 'vue'
import { getDevices, postDevices, startTask, stopTask, type Device } from '../script/api'
import { VueDraggable } from 'vue-draggable-plus'
import { useInterfaceStore, type TaskListItem } from '../stores/interface.ts'
import { useIndexStore } from '../stores'

const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const task_list = ref<TaskListItem[]>([])
const scroll_show = ref(window.innerWidth > 768)
const device = ref<Device | null>(null)
const resource = ref<object | null>(null)
const devices_list = ref<object[]>([])
const loading = ref(false)

// 监听 store 中的变化并更新本地数据
watch(
  () => interfaceStore.getTaskList,
  (newList) => {
    for (const task of newList) {
      task_list.value.push({ ...task, checked: true})
    }
    indexStore.SelectTask(task_list.value[0]!.id)
  },
)

// 同步回store
// watch(task_list, (newList) => {
//   interfaceStore.updateTaskList(newList)
// }, { deep: true })

function get_device() {
  devices_list.value = []
  loading.value = true
  getDevices().then((devices_data) => {
    for (const device of devices_data) {
      devices_list.value?.push({
        label: device.name + ' ' + device.address,
        value: device,
      })
    }
    loading.value = false
  })
}

function connectDevices() {
  postDevices(device.value as Device)
}

function get_resource() {
  //TODO
}

function post_resource() {
  //TODO
}
</script>
<style scoped>
.list-group-item i {
  cursor: pointer;
}
</style>
