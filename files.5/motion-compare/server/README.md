# Motion Compare Server

FastAPI + WebSocket server làm backend cho mobile app Expo.
Tái sử dụng module `motion-compare/` đã có.

## Setup

```bash
# Từ root project
pip install -r server/requirements.txt
# Lưu ý: ultralytics, opencv-python, numpy đã có trong env hiện tại
```

## Chuẩn bị preset (chạy 1 lần)

Server đọc các file `.npz` trong `motion-compare/presets/`. Build trước khi
chạy server:

```bash
python motion-compare/build_reference.py --video input-videos/Forehand-Drive.mp4
python motion-compare/build_reference.py --video input-videos/Drop-Topspin.mp4
```

## Chạy server

```bash
# Bind 0.0.0.0 để điện thoại trong cùng wifi truy cập được
python server/main.py
# hoặc
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Kiểm tra: mở browser http://localhost:8000/ -> thấy JSON liệt kê preset.

### Lấy IP LAN của laptop

- Windows: `ipconfig` -> tìm IPv4 (vd 192.168.1.10)
- macOS/Linux: `ifconfig | grep inet` hoặc `ip addr`

Điện thoại (cùng wifi) truy cập: `http://192.168.1.10:8000/` để test trước khi
chạy app.

## Endpoints

| Method | Path | Mô tả |
|---|---|---|
| GET | `/` | Health + list preset |
| GET | `/presets` | Chi tiết tất cả preset |
| GET | `/presets/{name}` | Metadata 1 preset |
| GET | `/refs/{name}.mp4` | Stream video ref gốc (nếu còn trên server) |
| GET | `/sessions/<id>/...` | Static files của session đã record |
| WS  | `/ws/compare` | WebSocket realtime compare |

## WebSocket protocol

### Client -> Server

**1. Init (gửi đầu tiên):**
```json
{"type": "init", "preset": "Forehand-Drive", "record": true}
```

**2. Frame (lặp):**
```json
{"type": "frame", "image": "<base64 JPEG>", "client_ts": 1731600000123}
```

**3. Stop:**
```json
{"type": "stop"}
```

### Server -> Client

**Ready (sau init):**
```json
{"type": "ready", "ref_name": "Forehand-Drive", "num_frames": 120, "fps": 30.0, "width": 1280, "height": 720}
```

**Result (mỗi frame):**
```json
{
  "type": "result",
  "ref_idx": 42,
  "num_ref": 120,
  "overall": 78.5,
  "per_joint": [null, 90.1, 88.0, ...],
  "feedback": ["Cổ tay phải: hạ thấp hơn (47%)."],
  "kpts": [[320.1, 240.5], ...],
  "kpts_conf": [0.95, 0.92, ...],
  "frame_w": 640,
  "frame_h": 480,
  "valid": true,
  "client_ts": 1731600000123
}
```

**Done (hết reference):**
```json
{"type": "done", "ref_idx": 119}
```

**Session (sau khi client gửi stop):**
```json
{"type": "session", "session": "20250520-103045", "report_url": "/sessions/.../report.json", "video_url": "/sessions/.../side_by_side.mp4", "num_frames": 372}
```

**Error:**
```json
{"type": "error", "msg": "..."}
```

## Test nhanh bằng wscat

```bash
npm i -g wscat
wscat -c ws://localhost:8000/ws/compare
> {"type":"init","preset":"Forehand-Drive"}
< {"type":"ready",...}
```

## Lưu ý hiệu năng

- Trên CPU laptop trung bình, server xử lý ~10-15 FPS với `yolov8n-pose.pt`.
- App nên gửi ~10 FPS (mỗi 100ms) để không chất đống message.
- Nếu có GPU, đặt biến môi trường `CUDA_VISIBLE_DEVICES=0` trước khi chạy.
