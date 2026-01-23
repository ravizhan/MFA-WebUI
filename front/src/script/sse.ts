export class SSEClient {
  private eventSource: EventSource | null = null;
  private url: string;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();
  private reconnectInterval: number = 3000;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;

  constructor(url: string) {
    this.url = url;
    this.connect();
  }

  private connect(): void {
    this.eventSource = new EventSource(this.url);

    this.eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.dispatchEvent(data.type, data);
      } catch (error) {
        console.error('SSE消息解析错误:', error);
      }
    };

    this.eventSource.onopen = () => {
      console.log('SSE连接成功');
      this.reconnectAttempts = 0;
    };

    this.eventSource.onerror = (error) => {
      console.error('SSE连接错误:', error);
      this.eventSource?.close();
      
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        setTimeout(() => {
          this.reconnectAttempts++;
          console.log(`SSE重连尝试 ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
          this.connect();
        }, this.reconnectInterval);
      } else {
        console.error('SSE重连失败次数过多，停止尝试');
      }
    };
  }

  public addEventListener(type: string, callback: (data: any) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)?.add(callback);
  }

  public removeEventListener(type: string, callback: (data: any) => void): void {
    this.listeners.get(type)?.delete(callback);
  }

  private dispatchEvent(type: string, data: any): void {
    this.listeners.get(type)?.forEach(callback => callback(data));
  }

  public close(): void {
    this.eventSource?.close();
    this.eventSource = null;
  }
}

export const sse = new SSEClient('/api/logs');

sse.addEventListener('log', (data) => console.log('收到日志消息:', data.message));