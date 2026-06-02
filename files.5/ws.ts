// WebSocket client cho /ws/compare
// Wrap chuẩn để screen chỉ cần lắng nghe events.

export type InitMsg = { type: 'init'; preset: string; record?: boolean };
export type FrameMsg = { type: 'frame'; image: string; client_ts: number };
export type StopMsg = { type: 'stop' };
export type ClientMsg = InitMsg | FrameMsg | StopMsg;

export type ReadyEv = {
  type: 'ready';
  ref_name: string;
  num_frames: number;
  fps: number;
  width: number;
  height: number;
};
export type ResultEv = {
  type: 'result';
  ref_idx: number;
  num_ref: number;
  overall: number;
  per_joint: Array<number | null>;
  feedback: string[];
  kpts: Array<[number, number]>;
  kpts_conf: number[];
  frame_w: number;
  frame_h: number;
  valid: boolean;
  client_ts: number | null;
};
export type DoneEv = { type: 'done'; ref_idx: number };
export type SessionEv = {
  type: 'session';
  session: string;
  report_url: string;
  video_url: string;
  num_frames: number;
};
export type ErrorEv = { type: 'error'; msg: string };
export type ServerEv = ReadyEv | ResultEv | DoneEv | SessionEv | ErrorEv;

export type CompareHandlers = {
  onReady?: (e: ReadyEv) => void;
  onResult?: (e: ResultEv) => void;
  onDone?: (e: DoneEv) => void;
  onSession?: (e: SessionEv) => void;
  onError?: (msg: string) => void;
  onClose?: () => void;
  onOpen?: () => void;
};

export class CompareSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: CompareHandlers;
  private opened = false;

  constructor(serverUrl: string, handlers: CompareHandlers) {
    // serverUrl ví dụ "http://192.168.1.10:8000" -> chuyển sang ws://
    const wsBase = serverUrl.replace(/^http/, 'ws');
    this.url = `${wsBase}/ws/compare`;
    this.handlers = handlers;
  }

  connect(): void {
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.opened = true;
      this.handlers.onOpen?.();
    };
    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data as string) as ServerEv;
        switch (data.type) {
          case 'ready':   this.handlers.onReady?.(data); break;
          case 'result':  this.handlers.onResult?.(data); break;
          case 'done':    this.handlers.onDone?.(data); break;
          case 'session': this.handlers.onSession?.(data); break;
          case 'error':   this.handlers.onError?.(data.msg); break;
        }
      } catch (e) {
        this.handlers.onError?.(`Parse error: ${String(e)}`);
      }
    };
    this.ws.onerror = () => {
      this.handlers.onError?.('WebSocket error');
    };
    this.ws.onclose = () => {
      this.opened = false;
      this.handlers.onClose?.();
    };
  }

  send(msg: ClientMsg): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(msg));
  }

  isOpen(): boolean {
    return this.opened && this.ws?.readyState === WebSocket.OPEN;
  }

  close(): void {
    try {
      this.send({ type: 'stop' });
    } catch {
      // ignore
    }
    try {
      this.ws?.close();
    } catch {
      // ignore
    }
    this.ws = null;
    this.opened = false;
  }
}
