import type { InterfaceModel } from '../types/interfaceV2'

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
  status: string
  devices: Device[]
}

interface ResourceResponse {
  status: string
  resource: string[]
}

export function startTask(task_list: string[], options: Record<string, string>): void {
  fetch('/api/start', {
    method: 'POST',
    body: JSON.stringify({ tasks: task_list, options: options }),
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        // @ts-ignore
        window.$message.success('任务开始')
      } else {
        // @ts-ignore
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
        // @ts-ignore
        window.$message.success('正在中止任务，请稍后')
      } else {
        // @ts-ignore
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
        // @ts-ignore
        window.$message.success('设备连接成功')
      } else {
        // @ts-ignore
        window.$message.error('设备连接成功，请检查终端日志')
      }
    })
}

export function getInterface(): Promise<InterfaceModel> {
  return fetch('/api/interface', { method: 'GET' }).then((res) => res.json())
}

export function getResource(): Promise<string[]> {
  return fetch('/api/resource', { method: 'GET' })
    .then((res) => res.json())
    .then((data: ResourceResponse) => data.resource)
}

export function postResource(name: string): void {
  fetch('/api/resource?name='+name, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === 'success') {
        // @ts-ignore
        window.$message.success('资源添加成功')
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}