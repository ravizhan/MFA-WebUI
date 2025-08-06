<template>
  <div class="col-name">任务列表</div>
  <div style="padding: 0 2.5% 0 2.5%">
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
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import { VueDraggable } from 'vue-draggable-plus'

const message = useMessage()

const task_list = ref(null)
task_list.value = ['1', '2', '3', '4'].map((name, index) => {
  return { name, order: index + 1 }
})

function startTask() {
  fetch('/api/start', {
    method: 'POST',
    body: JSON.stringify({ tasklist: task_list }),
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data) => {
      if (data['status'] === 'success') {
        message.success('任务开始')
      } else {
        message.error(data['message'])
      }
    })
}

function stopTask() {
  fetch('/api/stop', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data) => {
      if (data['status'] === 'success') {
        message.success('正在中止任务，请稍后')
      } else {
        message.error(data['message'])
      }
    })
}
</script>
<style scoped>
.list-group-item i {
  cursor: pointer;
}
</style>
