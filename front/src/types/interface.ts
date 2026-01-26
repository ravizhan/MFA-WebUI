export type Win32MouseKeyboard =
  | "Seize"
  | "SendMessage"
  | "PostMessage"
  | "LegacyEvent"
  | "PostThreadMessage"
  | "SendMessageWithCursorPos"
  | "PostMessageWithCursorPos"

export type Win32Screencap =
  | "GDI"
  | "FramePool"
  | "DXGI_DesktopDup"
  | "DXGI_DesktopDup_Window"
  | "PrintWindow"
  | "ScreenDC"

export interface Win32Controller {
  class_regex?: string
  window_regex?: string
  mouse?: Win32MouseKeyboard
  keyboard?: Win32MouseKeyboard
  screencap?: Win32Screencap
}

export interface PlayCoverController {
  uuid?: string
}

export type GamepadType = "Xbox360" | "DualShock4" | "DS4"

export interface GamepadController {
  class_regex?: string
  window_regex?: string
  gamepad_type?: GamepadType
  screencap?: Win32Screencap
}

export type ControllerType = "Adb" | "Win32" | "PlayCover" | "Gamepad"

export interface Controller {
  name: string
  label?: string
  description?: string
  icon?: string
  type: ControllerType
  adb?: Record<string, any>
  win32?: Win32Controller
  playcover?: PlayCoverController
  gamepad?: GamepadController
  display_short_side?: number
  display_long_side?: number
  display_raw?: boolean
  permission_required?: boolean
}

export interface Resource {
  name: string
  label?: string
  description?: string
  icon?: string
  path: string[]
  controller?: string[]
  option?: string[]
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
  doc?: string | string[]
  icon?: string
  resource?: string[]
  controller?: string[]
  pipeline_override?: Record<string, object>
  option?: string[]
}

export interface OptionCase {
  name: string
  label?: string
  description?: string
  icon?: string
  option?: string[]
  pipeline_override?: Record<string, object>
}

export type InputPipelineType = "string" | "int" | "bool"

export interface InputCase {
  name: string
  label?: string
  description?: string
  default?: string
  pipeline_type?: InputPipelineType
  verify?: string
  pattern_msg?: string
}

interface OptionBase {
  label?: string
  description?: string
  icon?: string
  pipeline_override?: Record<string, object>
}

export interface SelectOption extends OptionBase {
  type: "select"
  cases: OptionCase[]
  default_case?: string
}

export interface InputOption extends OptionBase {
  type: "input"
  inputs: InputCase[]
}

export interface SwitchOption extends OptionBase {
  type: "switch"
  cases: [OptionCase, OptionCase]
  default_case?: string
}

export type Option = SelectOption | InputOption | SwitchOption

export interface InterfaceModel {
  interface_version: 2
  languages?: Record<string, string>
  name: string
  label?: string
  title?: string
  icon?: string
  mirrorchyan_rid?: string
  mirrorchyan_multiplatform?: boolean
  github?: string
  version?: string
  contact?: string
  license?: string
  welcome?: string
  description?: string
  controller: Controller[]
  resource: Resource[]
  agent?: Agent
  task: Task[]
  option?: Record<string, Option>
}
