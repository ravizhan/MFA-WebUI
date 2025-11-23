export interface AdbController {
  input?: number
  screencap?: number
  config?: Record<string, string>
}

export interface Win32Controller {
  class_regex?: string
  window_regex?: string
  mouse?: number
  keyboard?: number
  screencap?: number
}

interface Controller {
  name: string
  label: string
  description?: string
  icon: string
  type: string
  adb?: AdbController
  win32?: Win32Controller
  display_short_side?: undefined
  display_long_side?: undefined
  display_raw?: undefined
}

export interface Resource {
  name: string
  label?: string
  description?: string
  icon?: string
  path: string[]
  controller?: string[]
}

export interface Agent {
  child_exec: string
  child_args?: string[]
  identifier?: string
}

export interface Task {
  name: string
  label?: string
  entry: string
  default_check?: boolean
  description?: string
  icon?: string
  resource?: string[]
  pipeline_override?: Record<string, object>
  option?: string[]
}

export interface OptionCase {
  name: string
  label?: string
  description?: string
  icon?: string
  options?: Record<string, string>
  pipeline_override: Record<string, object>
}

export type InputPipelineType = 'str' | 'int' | 'float'

export interface InputCase {
  name: string
  label?: string
  description?: string
  default?: string
  pipeline_type?: InputPipelineType
  verify?: string
}

interface OptionBase {
  key: string
  label?: string
  description?: string
  icon?: string
}

export interface SelectOption extends OptionBase {
  type: 'select'
  cases: OptionCase[]
  default_case?: string
}

export interface InputOption extends OptionBase {
  type: 'input'
  inputs: InputCase[]
  pipeline_override?: Record<string, object>
}

export type Option = SelectOption | InputOption

export interface InterfaceModel {
  interface_version: number
  languages?: Record<string, string>
  name: string
  label?: string
  title?: string
  icon?: string
  mirrorchyan_rid?: string
  mirrorchyan_multiplatform?: boolean
  auto_update_ui: boolean
  auto_update_maafw: boolean
  github: string
  version: string
  contact: string
  license: string
  welcome: string
  description: string
  controller: Controller[]
  resource: Resource[]
  agent?: Agent
  task: Task[]
  option: Record<string, Option>
}

