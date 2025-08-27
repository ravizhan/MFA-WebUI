import { useMessage } from 'naive-ui'
import type { InterfaceModel } from '../types/interfaceV1'

const message = useMessage()
interface ApiResponse {
  status: string
  message: string
}

interface Device {
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
  }).then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        message.success('任务开始')
      } else {
        message.error(data.message)
      }
    })
}

export function stopTask(): void {
  fetch('/api/stop', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  }).then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        message.success('正在中止任务，请稍后')
      } else {
        message.error(data.message)
      }
    })
}

export function getDevices(): Promise<Device[]> {
  return fetch('/api/device', {method: 'GET',})
    .then((res) => res.json())
    .then((data: DeviceResponse) => data.devices)
}

export function postDevices(devices: Device[]): void {
  fetch('/api/device', {
    method: 'POST',
    body: JSON.stringify({ devices: devices }),
    headers: {
      'Content-Type': 'application/json',
    },
  }).then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        message.success('设备连接成功')
      } else {
        message.error('设备连接成功，请检查终端日志')
      }
    })
}

export function getInterface(): Promise<InterfaceModel> {
  return fetch('/api/interface', { method: 'GET' })
    .then((res) => res.json())
}
