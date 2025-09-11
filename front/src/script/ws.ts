import { ConstantBackoff, WebsocketBuilder, WebsocketEvent } from 'websocket-ts'

export const ws = new WebsocketBuilder('ws://127.0.0.1:55666/api/ws')
  .withBackoff(new ConstantBackoff(1000))
  .build()

ws.addEventListener(WebsocketEvent.open, () => console.log('websocket连接成功'))
ws.addEventListener(WebsocketEvent.close, () => console.log('websocket连接关闭'))
ws.addEventListener(WebsocketEvent.error, (err) => console.log('websocket连接错误', err))
