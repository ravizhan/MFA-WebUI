import { useMessage } from 'naive-ui'
const message = useMessage()

export function startTask(task_list) {
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

export function stopTask() {
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

export function getDevices() {
  return fetch('/api/get_device', {
    method: 'GET',
  }).then((res) => res.json())
}

export function connectDevices() {
  if (model.value.device === null) {
    message.error('请选择一个设备')
  } else {
    fetch('/api/connect_device', {
      method: 'POST',
      body: JSON.stringify(model.value.device),
      headers: {
        'Content-Type': 'application/json',
      },
    })
      .then((res) => res.json())
      .then((data) => {
        if (data['status'] === 'success') {
          message.success('连接成功')
        } else {
          message.error('连接失败')
        }
      })
  }
}

export function getInfo() {
  return fetch('/api/info', {
    method: 'GET',
  }).then((res) => res.json())
}