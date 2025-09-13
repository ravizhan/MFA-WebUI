interface Controller {
  name: string
  type: string
}

interface Resource {
  name: string
  path: string[]
}

interface Agent {
  child_exec: string
  child_args: string[]
}

export interface Task {
  name: string
  entry: string
  doc?: string | string[]
  option?: string[]
  pipeline_override?: Record<string, object>
  repeatable?: boolean
  repeat_count?: number
}

export interface OptionCase {
  name: string
  pipeline_override: Record<string, object>
}

export interface Option {
  default_case?: string
  cases: OptionCase[]
}

export interface InterfaceModel {
  name: string
  url: string
  mirrorchyan_rid?: string
  mirrorchyan_multiplatform?: boolean
  controller: Controller[]
  resource: Resource[]
  agent?: Agent
  task: Task[]
  option: Record<string, Option>
  version: string
}
