# Pickelball

Repo này gồm 2 phần chính:

1) **Pickleball Web App** (ASP.NET Core Razor Pages) — trang web học kỹ thuật/ bài tập pickleball.
2) **Motion Compare** (Python) — hệ thống so sánh tư thế realtime giữa người dùng và 1 motion mẫu:
  - `motion-compare/`: module build preset (.npz), so sánh pose, sinh feedback, lưu session.
  - `server/`: FastAPI + WebSocket backend (`/ws/compare`).

## Yêu cầu

- **Web App**: .NET SDK **10** (project target `net10.0`).
- **Motion Compare**:
  - Python 3.10+ (khuyến nghị)
  - Node.js 18+ (optional, used earlier for mobile tooling)
  - Các package ML/vision (tuỳ máy): `ultralytics`, `opencv-python`, `numpy`
  - Model: `yolov8n-pose.pt` (nếu chưa có thì cần tải về trước khi chạy server/module)

## Chạy Pickleball Web App

Từ root repo:

```bash
dotnet watch run --project PickleballWebApp
```

Mở:
- https://localhost:7119
- hoặc http://localhost:5215

## Chạy Motion Compare (server + mobile app)

### 1) Tạo preset (chạy 1 lần cho mỗi video reference)

```bash
python motion-compare/build_reference.py --video <path-to-video>.mp4
```

Preset sẽ được lưu vào `motion-compare/presets/<name>.npz`.

### 2) Chạy server

```bash
pip install -r server/requirements.txt
python server/main.py
# hoặc: uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Test nhanh: mở http://localhost:8000/ (phải thấy JSON).

### 3) Web client (optional)

Bạn có thể sử dụng web client served by the Python server at `/web`. Open `http://<host>:8000/web` to access the browser-based Motion Compare client which uses your webcam and connects to `/ws/compare`.

## Tài liệu chi tiết

- `PickleballWebApp/README.md`
- `server/README.md`
- `motion-compare/README.md`
- `motion-compare/README.md`
