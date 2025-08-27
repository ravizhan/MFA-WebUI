<template>
  <n-card content-style="padding: 0;" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" tab="设备连接">
        <div class="select-border">
          <div style="display: flex; align-items: center; gap: 8px">
            <n-select
              v-model:value="device"
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
              v-model:value="resource"
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
    <n-list hoverable bordered>
      <template v-if="scroll_show">
        <n-scrollbar class="max-h-80">
          <VueDraggable v-model="task_list">
            <n-list-item v-for="item in task_list" :key="item.id">
              <n-checkbox size="large" :label="item.name" />
              <template #suffix>
                <n-button quaternary circle>
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
            <n-checkbox size="large" :label="item.name" />
            <template #suffix>
              <n-button quaternary circle>
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
import { watch, onMounted, ref } from 'vue'
import { getDevices, postDevices, startTask, stopTask } from '../script/api'
import { VueDraggable } from 'vue-draggable-plus'
import { useInterfaceStore, type TaskListItem } from '../stores/interface.ts'

const interfaceStore = useInterfaceStore()
const task_list = ref<TaskListItem[]>()
const scroll_show = ref(window.innerWidth > 768)
const device = ref<object | null>(null)
const resource = ref<object | null>(null)
const devices_list = ref<object[] | null>(null)
const loading = ref(false)

// 监听 store 中的变化并更新本地数据
watch(
  () => interfaceStore.getTaskList,
  (newList) => {
    task_list.value = [...newList]
  },
  { immediate: true },
)

// 同步回store
// watch(task_list, (newList) => {
//   interfaceStore.updateTaskList(newList)
// }, { deep: true })

function get_device() {
  getDevices().then((devices_data) => {
    console.log(devices_data)
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
  postDevices(device)
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
