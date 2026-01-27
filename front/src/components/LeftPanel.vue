<template>
  <n-card content-style="padding: 0;margin: 5px" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" tab="设备连接">
        <n-flex class="pb-[12px]">
          <n-tree-select
            v-model:value="device"
            placeholder="请选择一个设备"
            :options="devices_tree"
            :loading="loading"
            :override-default-node-click-behavior="override"
            remote
            indent="6"
            @click="get_device"
            class="max-w-80%"
          />
          <n-button strong secondary type="info" @click="connectDevices">连接</n-button>
        </n-flex>
      </n-tab-pane>
      <n-tab-pane name="resource" tab="资源选择">
        <n-flex class="pb-[12px]">
          <n-select
            v-model:value="resource"
            placeholder="请选择一个资源"
            :options="resources_list"
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
        <n-scrollbar trigger="none" class="max-h-75">
          <VueDraggable v-model="configStore.taskList">
            <n-list-item v-for="item in configStore.taskList" :key="item.id">
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
        </n-scrollbar>
      </template>
      <template v-else>
        <VueDraggable v-model="configStore.taskList">
          <n-list-item v-for="item in configStore.taskList" :key="item.id">
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
      <n-button strong secondary type="info" size="large" @click="StartTask">开始任务</n-button>
      <n-button strong secondary type="info" size="large" @click="stopTask">中止任务</n-button>
    </n-flex>
    <n-flex class="form-btn" justify="center">
      <n-button quaternary type="warning" size="small" @click="resetConfig">重置配置</n-button>
    </n-flex>
  </n-card>
</template>
<script setup lang="ts">
import { watch, ref } from "vue"
import {
  getDevices,
  postDevices,
  startTask,
  stopTask,
  type AdbDevice,
  type Win32Device,
  getResource,
  postResource,
} from "../script/api"
import { VueDraggable } from "vue-draggable-plus"
import { useUserConfigStore } from "../stores/userConfig"
import { useIndexStore } from "../stores"
import type { TreeSelectOverrideNodeClickBehavior } from "naive-ui"
import { useMessage, useDialog } from "naive-ui"
if (typeof window !== "undefined") {
  window.$message = useMessage()
}

const dialog = useDialog()
const configStore = useUserConfigStore()
const indexStore = useIndexStore()
const scroll_show = ref(window.innerWidth > 768)
const device = ref<AdbDevice | Win32Device | null>(null)
const resource = ref<string | null>(null)
const devices_tree = ref<object[]>([])
const resources_list = ref<object[]>([])
const loading = ref(false)
const override: TreeSelectOverrideNodeClickBehavior = ({ option }) => {
  if (option.children) {
    return "toggleExpand"
  }
  return "default"
}

watch(
  () => configStore.taskList,
  (newList) => {
    if (newList.length) {
      indexStore.SelectTask(newList[0]!.id)
    }
  },
  { immediate: true },
)

watch(
  () => configStore.taskList,
  () => {
    if (configStore.configLoaded) {
      configStore.debouncedSave()
    }
  },
  { deep: true },
)

watch(
  () => configStore.options,
  () => {
    if (configStore.configLoaded) {
      configStore.debouncedSave()
    }
  },
  { deep: true },
)

function get_device() {
  devices_tree.value = [
    {
      label: "Adb",
      key: "Adb",
      children: [],
    },
    {
      label: "Win32",
      key: "Win32",
      children: [],
    },
  ]
  loading.value = true
  getDevices().then((devices_data) => {
    for (const dev of devices_data.adb) {
      (devices_tree.value[0] as any).children.push({
        label: dev.name + " (" + dev.address + ")",
        key: dev,
      })
    }
    for (const dev of devices_data.win32) {
      (devices_tree.value[1] as any).children.push({
        label: dev.window_name + " (" + dev.class_name + ")",
        key: dev,
      })
    }
  }).then(() => {
      if ((devices_tree.value[0] as any).children.length === 0) {
    (devices_tree.value[0] as any).children.push({
      label: "无可用设备",
      key: "none",
      disabled: true,
    })
  }
  if ((devices_tree.value[1] as any).children.length === 0) {
    (devices_tree.value[1] as any).children.push({
      label: "无可用设备",
      key: "none",
      disabled: true,
    })
  }
  loading.value = false
  })
}

function connectDevices() {
  if (!device.value) {
    // @ts-ignore
    window.$message.error("请选择一个设备")
    return
  } else {
    postDevices(device.value).then((success) => {
      indexStore.setConnected(success)
    })
  }
}

function get_resource() {
  resources_list.value = []
  loading.value = true
  getResource().then((resource_data) => {
    for (const resource of resource_data) {
      resources_list.value?.push({
        label: resource,
        value: resource,
      })
    }
  })
  loading.value = false
}

function post_resource() {
  if (!resource.value) {
    // @ts-ignore
    window.$message.error("请选择一个资源")
    return
  } else {
    postResource(resource.value)
  }
}

function StartTask() {
  const selectedTasks = configStore.taskList.filter((task) => task.checked).map((task) => task.id)
  if (selectedTasks.length === 0) {
    // @ts-ignore
    window.$message.error("请至少选择一个任务")
    return
  }
  startTask(selectedTasks, configStore.options)
}

function resetConfig() {
  dialog.warning({
    title: "重置配置",
    content: "确定要重置所有任务配置吗？此操作不可撤销。",
    positiveText: "确定",
    negativeText: "取消",
    onPositiveClick: async () => {
      await configStore.resetConfig()
      // @ts-ignore
      window.$message.success("配置已重置")
    },
  })
}
</script>
<style scoped>
.list-group-item i {
  cursor: pointer;
}
.form-btn {
  text-align: center;
  padding-top: 5%;
}

</style>
