# Motion Compare Module

Module so sánh tư thế (pose) real-time giữa người dùng và 1 motion mẫu.
Dùng YOLOv8 pose (COCO-17) cho cả webcam stream và reference video.

## Cấu trúc

```
motion-compare/
├── README.md
├── pose_utils.py        # COCO-17 indices, skeleton edges, vẽ skeleton có màu
├── reference.py         # ReferenceMotion: build/save/load .npz
├── comparator.py        # Engine: normalize pose, distance, velocity, score
├── feedback.py          # Sinh feedback tiếng Việt theo joint
├── recorder.py          # SessionRecorder: side-by-side video + JSON
├── build_reference.py   # CLI build preset từ 1 video
├── app.py               # UI Tkinter 2 pane (entry point)
├── presets/             # .npz preset (tự tạo)
└── sessions/            # Output session (tự tạo)
```

## Yêu cầu

Dùng env hiện có của project (đã có `ultralytics`, `opencv-python`, `numpy`,
`yolov8n-pose.pt`). Bổ sung:

```bash
pip install pillow
```

`tkinter` thường đi kèm Python. Linux có thể cần `sudo apt install python3-tk`.

## Khởi động nhanh

### 1) Build 1 preset từ video sẵn có

```bash
# Ví dụ dùng video pickleball đã có
python motion-compare/build_reference.py --video input-videos/Forehand-Drive.mp4
python motion-compare/build_reference.py --video input-videos/Drop-Topspin.mp4 --name drop_topspin
```

Preset được lưu vào `motion-compare/presets/<name>.npz`.

### 2) Mở app

```bash
python motion-compare/app.py
# hoặc load thẳng preset
python motion-compare/app.py --preset Forehand-Drive
# hoặc build trên-the-fly rồi mở app
python motion-compare/app.py --ref-video input-videos/Roll-Volley.mp4
```

Trong app:
- Chọn preset từ dropdown rồi bấm **Load preset**.
- Bấm **▶ Start** (hoặc `Space`) để bắt đầu webcam + so sánh.
- **■ Stop** (hoặc `Space`) để dừng. Khi đó video side-by-side + report JSON
  được lưu vào `motion-compare/sessions/<timestamp>/`.

Phím tắt: `Space` start/stop, `M` toggle gương webcam, `Esc` đóng app.

## UI layout

**Bên trái** — webcam realtime:
- Frame webcam + skeleton overlay (17 keypoints + edges).
- Mỗi joint tô màu theo accuracy: xanh ≥80%, vàng 50–80%, đỏ <50%.
- Overlay HUD: overall accuracy, FPS, frame number, ref frame index.

**Bên phải** — bảng phân tích:
- Progress bar: `ref_frame / total_ref_frames`.
- Overall accuracy (chữ to, đổi màu theo điểm).
- Per-joint breakdown 7 nhóm: Đầu, Vai, Khuỷu tay, Cổ tay, Hông, Đầu gối, Cổ chân.
- Feedback tiếng Việt: top 2 joint sai nhất + hướng cần sửa, ví dụ:
  `Cổ tay phải: nâng cao hơn (62%).`

## Engine so sánh — tóm tắt

Mỗi frame `t`:

1. **Normalize pose**: hip-center về gốc, chia cho `torso length` (vai-hông).
   Đảm bảo bất biến với vị trí + scale của người trong khung hình.
2. **Position distance** mỗi joint: `||user_norm[i] - ref_norm[i]||`.
3. **Velocity distance** mỗi joint: chênh lệch `(pos[t] - pos[t-1])` giữa user và ref.
4. **Score / joint**: `(1-α)*exp(-k₁·d_pos) + α*exp(-k₂·d_vel)` rồi nhân 100.
5. **Overall**: trung bình per-joint, trọng số = `min(user_conf, ref_conf)`.
   Joint có confidence thấp được đánh dấu `NaN` (n/a) và không tính vào overall.

Tham số trong `comparator.py`:
- `_DECAY_POS = 2.5`, `_DECAY_VEL = 4.0`, `_VEL_WEIGHT = 0.30`.

## Pacing reference

App đồng bộ ref theo **thời gian thực** kể từ lúc Start:
`ref_idx = floor((t_now - t_start) * ref_fps)`. Khi hết ref → tự Stop, hoặc
loop nếu bật **Loop ref**. Không dùng DTW — phù hợp với pattern "tập theo nhịp".

## Output sau mỗi session

`motion-compare/sessions/YYYYMMDD-HHMMSS/`:
- `side_by_side.mp4` — video ghép [user_annotated | reference_annotated], 1280×480.
- `report.json` — schema:
  ```json
  {
    "started_at": 1731600000.0,
    "duration_sec": 12.4,
    "fps": 30.0,
    "num_frames": 372,
    "avg_accuracy": 78.3,
    "frames": [
      {
        "frame": 0,
        "ref_frame": 0,
        "accuracy": 81.2,
        "valid": true,
        "per_joint": [null, 90.1, 88.0, ...],   // độ dài 17, COCO order, null = n/a
        "feedback": ["Cổ tay phải: hạ thấp hơn (58%)."],
        "t": 0.034
      }
    ]
  }
  ```

### Replay theo section

Để tìm các đoạn điểm thấp:

```python
import json, statistics
r = json.load(open("motion-compare/sessions/.../report.json", encoding="utf-8"))
bad = [f for f in r["frames"] if f["valid"] and f["accuracy"] < 60]
print(len(bad), "frames < 60%")
# rồi seek vào side_by_side.mp4 theo frame index để xem lại
```

## Hiệu năng

- YOLOv8n-pose trên GPU: thường ≥ 30 FPS với webcam 640×480.
- CPU: ~10–15 FPS. App vẫn chạy mượt nhờ:
  - Pose chạy ở worker thread, UI poll qua queue.
  - UI chỉ render frame mới nhất, bỏ frame cũ nếu thread chính bận.
  - Reference frame đọc tuần tự (grab + read), seek chỉ khi cần lùi.

Nếu chậm, có thể đổi sang model nhỏ hơn (đã có sẵn `yolov8n-pose.pt`) hoặc
hạ độ phân giải webcam.

## Lưu ý về gương (mirror)

- Webcam thường cho ảnh **không gương** (giống cách người khác nhìn bạn).
- Bật **Gương webcam** sẽ lật ngang cả ảnh hiển thị lẫn keypoints trước khi
  inference → khớp với cảm giác "nhìn gương".
- Nếu video reference quay người **hướng cùng chiều** với webcam thì
  KHÔNG bật gương; nếu reference đã được lật sẵn thì bật.

## Mở rộng

- Thêm preset bằng cách chạy `build_reference.py` với video bất kỳ
  (pushup, squat, serve, hoặc các shot pickleball).
- Tinh chỉnh feedback bằng cách sửa ngưỡng `_NEEDS_FIX_TH` và
  `_MIN_OFFSET_NORM` trong `feedback.py`.
- Đổi công thức scoring trong `comparator.py` (decay, vel_weight).
