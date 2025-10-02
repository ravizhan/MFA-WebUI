import type { InterfaceModel } from '../types/interfaceV1'

interface ApiResponse {
  status: string
  message: string
}

export interface Device {
  name: string
  adb_path: string
  address: string
  screencap_methods: string
  input_methods: string
  config: object
}

interface DeviceResponse {
  devices: Device[]
}

export function startTask(task_list: object[]): void {
  fetch('/api/start', {
    method: 'POST',
    body: JSON.stringify({ tasklist: task_list }),
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        window.$message.success('任务开始')
      } else {
        window.$message.error(data.message)
      }
    })
}

export function stopTask(): void {
  fetch('/api/stop', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        window.$message.success('正在中止任务，请稍后')
      } else {
        window.$message.error(data.message)
      }
    })
}

export function getDevices(): Promise<Device[]> {
  return fetch('/api/device', { method: 'GET' })
    .then((res) => res.json())
    .then((data: DeviceResponse) => data.devices)
}

export function postDevices(device: Device): void {
  fetch('/api/device', {
    method: 'POST',
    body: JSON.stringify(device),
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        window.$message.success('设备连接成功')
      } else {
        window.$message.error('设备连接成功，请检查终端日志')
      }
    })
}

export function getInterface(): Promise<InterfaceModel> {
  return fetch('/api/interface', { method: 'GET' }).then((res) => res.json())
}
