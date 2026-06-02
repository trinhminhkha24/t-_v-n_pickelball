"""FastAPI server cho Motion Compare.

Endpoints:
    GET  /                 - health check + thông tin server
    GET  /presets          - list các preset .npz có sẵn
    GET  /presets/{name}   - metadata 1 preset (num_frames, fps, ...)
    POST /compare-video    - upload video file để so sánh với preset (trả JSON kết quả)
    WS   /ws/compare       - WebSocket cho realtime comparison

WebSocket protocol:
    Client gửi JSON đầu tiên: {"type": "init", "preset": "Forehand-Drive", "mirror": false}
    Server reply:              {"type": "ready", "num_frames": N, "fps": 30.0, "ref_name": "..."}

    Sau đó mỗi frame webcam, client gửi:
        {"type": "frame", "image": "<base64 JPEG>", "client_ts": <unix_ms>}
    Server reply (cho mỗi frame):
        {
          "type": "result",
          "ref_idx": int,             # frame index của ref đang so sánh
          "overall": float,           # 0-100
          "per_joint": [...17...],    # null nếu n/a
          "feedback": ["..."],
          "kpts": [[x,y], ...17...],  # toạ độ trên ảnh user (đã resize về kích thước gốc)
          "kpts_conf": [...17...],
          "valid": bool,
          "client_ts": <echo>
        }
    Client gửi {"type": "stop"} để kết thúc -> server gửi {"type": "session", "report_url": "..."}
"""

from __future__ import annotations

import base64
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Tái dùng module motion-compare
# server/main.py nằm ở files.5/motion-compare/server/ → đi lên 4 cấp để đến project root
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MC = _ROOT / "motion-compare"
sys.path.insert(0, str(_MC))

from comparator import compare_frame  # noqa: E402
from feedback import generate_feedback  # noqa: E402
from pose_utils import CONF_TH, pick_best_person  # noqa: E402
from recorder import SessionRecorder  # noqa: E402
from reference import PRESETS_DIR, ReferenceMotion  # noqa: E402


POSE_MODEL_PATH = _ROOT / "yolov8n-pose.pt"


# ---------- App ----------

app = FastAPI(title="Motion Compare Server")

# CORS mở cho dev (Expo có thể gọi từ nhiều IP)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy load model
_pose_model = None


def get_pose_model():
    global _pose_model
    if _pose_model is None:
        from ultralytics import YOLO
        print(f"[server] Loading pose model: {POSE_MODEL_PATH}")
        _pose_model = YOLO(str(POSE_MODEL_PATH))
    return _pose_model


# ---------- REST endpoints ----------

@app.get("/")
def root():
    presets = [p.stem for p in ReferenceMotion.list_presets()]
    return {
        "ok": True,
        "service": "motion-compare-server",
        "presets": presets,
        "pose_model": POSE_MODEL_PATH.name,
        "ts": time.time(),
    }


@app.get("/presets")
def list_presets():
    out = []
    for p in ReferenceMotion.list_presets():
        try:
            ref = ReferenceMotion.load(p)
            out.append({
                "name": ref.name,
                "num_frames": ref.num_frames,
                "fps": ref.fps,
                "width": ref.width,
                "height": ref.height,
                "duration_sec": round(ref.duration, 2),
            })
        except Exception as e:  # noqa: BLE001
            out.append({"name": p.stem, "error": str(e)})
    return {"presets": out}


@app.get("/presets/{name}")
def get_preset(name: str):
    path = PRESETS_DIR / f"{name}.npz"
    if not path.exists():
        raise HTTPException(404, f"Preset không tồn tại: {name}")
    ref = ReferenceMotion.load(path)
    return {
        "name": ref.name,
        "num_frames": ref.num_frames,
        "fps": ref.fps,
        "width": ref.width,
        "height": ref.height,
        "duration_sec": round(ref.duration, 2),
        "has_video": bool(ref.src_path) and Path(ref.src_path).exists(),
    }


@app.post("/compare-video")
async def compare_video(
    file: UploadFile = File(...),
    preset: str = Form(...),
    record: bool = Form(False),
):
    """Nhận video upload từ client, so sánh từng frame với preset, trả JSON kết quả.

    Response JSON:
    {
        "preset": str,
        "overall": float,           # điểm trung bình toàn video
        "num_frames_processed": int,
        "num_frames_valid": int,
        "fps_video": float,
        "duration_sec": float,
        "frames": [                 # mỗi frame người dùng đã được xử lý
            {
                "frame_idx": int,
                "ref_idx": int,
                "overall": float,
                "per_joint": [...17...],
                "feedback": [...],
                "kpts": [[x,y],...],
                "kpts_conf": [...],
                "valid": bool,
            },
            ...
        ],
        "session": {                # chỉ có khi record=True
            "video_url": str,
            "report_url": str,
        } | null,
    }
    """
    # Kiểm tra preset
    preset_path = PRESETS_DIR / f"{preset}.npz"
    if not preset_path.exists():
        raise HTTPException(404, f"Preset không tồn tại: {preset}")

    ref = ReferenceMotion.load(preset_path)
    pose = get_pose_model()

    # Lưu upload vào file tạm
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        cap = cv2.VideoCapture(str(tmp_path))
        if not cap.isOpened():
            raise HTTPException(400, "Không thể đọc file video. Đảm bảo định dạng được hỗ trợ (mp4, avi, mov).")

        fps_video = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        recorder: SessionRecorder | None = None
        if record:
            recorder = SessionRecorder(fps=fps_video, size=(1280, 480))

        results_frames = []
        overall_scores = []
        prev_user: np.ndarray | None = None
        prev_ref: np.ndarray | None = None
        frame_idx = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            # Tính ref_idx theo thời gian tương đối của video
            elapsed = frame_idx / fps_video
            ref_idx = int(elapsed * (ref.fps if ref.fps > 0 else 30.0))
            ref_idx = max(0, min(ref.num_frames - 1, ref_idx))

            # Pose estimation
            user_kpts = np.zeros((17, 2), dtype=np.float32)
            user_conf = np.zeros((17,), dtype=np.float32)
            res = pose.predict(frame, conf=CONF_TH, iou=0.7, verbose=False)
            if res and res[0].keypoints is not None and res[0].boxes is not None and len(res[0].boxes) > 0:
                boxes_xyxy = res[0].boxes.xyxy.cpu().numpy()
                kxy = res[0].keypoints.xy.cpu().numpy()
                kcf = (
                    res[0].keypoints.conf.cpu().numpy()
                    if res[0].keypoints.conf is not None
                    else np.ones(kxy.shape[:2], dtype=np.float32)
                )
                idx = pick_best_person(boxes_xyxy, kcf)
                if idx >= 0:
                    user_kpts = kxy[idx].astype(np.float32)
                    user_conf = kcf[idx].astype(np.float32)

            ref_kpts = ref.kpts[ref_idx]
            ref_conf = ref.conf[ref_idx]

            cmp = compare_frame(
                user_kpts, user_conf, ref_kpts, ref_conf,
                prev_user_kpts=prev_user, prev_ref_kpts=prev_ref,
            )
            fb = generate_feedback(cmp.per_joint, cmp.joint_offset)

            per_joint_list = [
                None if np.isnan(v) else round(float(v), 1)
                for v in cmp.per_joint.tolist()
            ]

            frame_result = {
                "frame_idx": frame_idx,
                "ref_idx": ref_idx,
                "overall": round(float(cmp.overall), 1),
                "per_joint": per_joint_list,
                "feedback": list(fb),
                "kpts": [[round(float(x), 1), round(float(y), 1)] for x, y in user_kpts.tolist()],
                "kpts_conf": [round(float(c), 3) for c in user_conf.tolist()],
                "valid": bool(cmp.valid),
            }
            results_frames.append(frame_result)

            if cmp.valid:
                overall_scores.append(cmp.overall)

            if recorder is not None:
                from pose_utils import draw_skeleton
                user_disp = frame.copy()
                draw_skeleton(user_disp, user_kpts, user_conf, joint_scores=cmp.per_joint)
                ref_disp = np.zeros((ref.height or 480, ref.width or 640, 3), dtype=np.uint8)
                draw_skeleton(ref_disp, ref_kpts, ref_conf, base_color=(220, 220, 220))
                recorder.write_frame(user_disp, ref_disp)
                recorder.add_entry(
                    frame_idx=frame_idx, ref_frame_idx=ref_idx,
                    accuracy=cmp.overall, per_joint=cmp.per_joint,
                    feedback=fb, valid=cmp.valid,
                )

            prev_user = user_kpts.copy()
            prev_ref = ref_kpts.copy()
            frame_idx += 1

        cap.release()

        overall_avg = float(np.mean(overall_scores)) if overall_scores else 0.0
        session_info = None
        if recorder is not None:
            out_dir = recorder.close()
            session_name = out_dir.name
            session_info = {
                "session": session_name,
                "report_url": f"/sessions/{session_name}/report.json",
                "video_url": f"/sessions/{session_name}/side_by_side.mp4",
            }

        return {
            "preset": preset,
            "overall": round(overall_avg, 1),
            "num_frames_processed": frame_idx,
            "num_frames_valid": len(overall_scores),
            "fps_video": fps_video,
            "duration_sec": round(frame_idx / fps_video, 2) if fps_video > 0 else 0.0,
            "frames": results_frames,
            "session": session_info,
        }

    finally:
        tmp_path.unlink(missing_ok=True)


# Phục vụ video reference (nếu cần - hữu ích khi dev test bằng browser)
@app.get("/refs/{name}.mp4")
def get_ref_video(name: str):
    path = PRESETS_DIR / f"{name}.npz"
    if not path.exists():
        raise HTTPException(404, "Preset không tồn tại")
    ref = ReferenceMotion.load(path)
    if not ref.src_path or not Path(ref.src_path).exists():
        raise HTTPException(404, "Reference video không có sẵn trên server")
    return FileResponse(ref.src_path, media_type="video/mp4")


# ---------- Admin endpoints ----------

@app.post("/admin/presets")
async def admin_create_preset(
    file: UploadFile = File(...),
    name: str = Form(""),
):
    """Upload video mẫu → chạy YOLOv8 → lưu .npz preset.

    Form fields:
        file  – video file (mp4/avi/mov)
        name  – tên preset (tùy chọn; mặc định = stem của file name)

    Response:
        { "name": str, "num_frames": int, "fps": float, "width": int, "height": int, "duration_sec": float }
    """
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    preset_name = (name.strip() or Path(file.filename or "preset").stem).replace(" ", "-")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(await file.read())

    try:
        from reference import build_from_video

        pose = get_pose_model()
        ref = build_from_video(video_path=tmp_path, pose_model=pose, name=preset_name, progress=False)

        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = PRESETS_DIR / f"{ref.name}.npz"
        ref.save(out_path)

        return {
            "name": ref.name,
            "num_frames": ref.num_frames,
            "fps": round(ref.fps, 2),
            "width": ref.width,
            "height": ref.height,
            "duration_sec": round(ref.duration, 2),
        }
    finally:
        tmp_path.unlink(missing_ok=True)


@app.delete("/admin/presets/{name}")
def admin_delete_preset(name: str):
    """Xóa preset .npz theo tên."""
    path = PRESETS_DIR / f"{name}.npz"
    if not path.exists():
        raise HTTPException(404, f"Preset không tồn tại: {name}")
    path.unlink()
    return {"deleted": name}


# Serve session output để client xem lại
_SESSIONS_DIR = _MC / "sessions"
if _SESSIONS_DIR.exists():
    app.mount("/sessions", StaticFiles(directory=str(_SESSIONS_DIR)), name="sessions")


# ---------- WebSocket: realtime compare ----------

@app.websocket("/ws/compare")
async def ws_compare(ws: WebSocket):
    await ws.accept()
    print("[ws] client connected")

    ref: ReferenceMotion | None = None
    recorder: SessionRecorder | None = None
    record_enabled = False

    prev_user: np.ndarray | None = None
    prev_ref: np.ndarray | None = None
    t0: float | None = None
    frame_count = 0

    try:
        # 1) Đợi init message
        init = await ws.receive_json()
        if init.get("type") != "init":
            await ws.send_json({"type": "error", "msg": "Expected init message first"})
            await ws.close()
            return

        preset_name = init.get("preset")
        record_enabled = bool(init.get("record", False))
        if not preset_name:
            await ws.send_json({"type": "error", "msg": "Missing 'preset'"})
            await ws.close()
            return

        preset_path = PRESETS_DIR / f"{preset_name}.npz"
        if not preset_path.exists():
            await ws.send_json({"type": "error", "msg": f"Preset không tồn tại: {preset_name}"})
            await ws.close()
            return

        ref = ReferenceMotion.load(preset_path)
        pose = get_pose_model()

        if record_enabled:
            recorder = SessionRecorder(fps=max(10.0, ref.fps), size=(1280, 480))

        await ws.send_json({
            "type": "ready",
            "ref_name": ref.name,
            "num_frames": ref.num_frames,
            "fps": ref.fps,
            "width": ref.width,
            "height": ref.height,
        })
        print(f"[ws] init OK -> preset={ref.name} frames={ref.num_frames} record={record_enabled}")

        # 2) Loop nhận frame
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "stop":
                break

            if mtype != "frame":
                continue

            b64 = msg.get("image", "")
            client_ts = msg.get("client_ts")
            if not b64:
                continue

            # Decode JPEG base64 -> ndarray BGR
            try:
                jpg = base64.b64decode(b64)
                arr = np.frombuffer(jpg, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    continue
            except Exception:
                continue

            if t0 is None:
                t0 = time.time()

            # Ref index theo thời gian thực kể từ frame đầu tiên nhận được
            elapsed = time.time() - t0
            ref_idx = int(elapsed * (ref.fps if ref.fps > 0 else 30.0))
            if ref_idx >= ref.num_frames:
                # hết ref -> báo done, không break (chờ client gửi stop hoặc init mới)
                await ws.send_json({"type": "done", "ref_idx": ref.num_frames - 1})
                continue
            ref_idx = max(0, min(ref.num_frames - 1, ref_idx))

            # Pose user
            user_kpts = np.zeros((17, 2), dtype=np.float32)
            user_conf = np.zeros((17,), dtype=np.float32)
            res = pose.predict(frame, conf=CONF_TH, iou=0.7, verbose=False)
            if res and res[0].keypoints is not None and res[0].boxes is not None and len(res[0].boxes) > 0:
                boxes_xyxy = res[0].boxes.xyxy.cpu().numpy()
                kxy = res[0].keypoints.xy.cpu().numpy()
                kcf = (
                    res[0].keypoints.conf.cpu().numpy()
                    if res[0].keypoints.conf is not None
                    else np.ones(kxy.shape[:2], dtype=np.float32)
                )
                idx = pick_best_person(boxes_xyxy, kcf)
                if idx >= 0:
                    user_kpts = kxy[idx].astype(np.float32)
                    user_conf = kcf[idx].astype(np.float32)

            ref_kpts = ref.kpts[ref_idx]
            ref_conf = ref.conf[ref_idx]

            cmp = compare_frame(
                user_kpts, user_conf, ref_kpts, ref_conf,
                prev_user_kpts=prev_user, prev_ref_kpts=prev_ref,
            )
            fb = generate_feedback(cmp.per_joint, cmp.joint_offset)

            # Build response
            per_joint_list = [
                None if np.isnan(v) else round(float(v), 1)
                for v in cmp.per_joint.tolist()
            ]
            response = {
                "type": "result",
                "ref_idx": ref_idx,
                "num_ref": ref.num_frames,
                "overall": round(float(cmp.overall), 1),
                "per_joint": per_joint_list,
                "feedback": list(fb),
                "kpts": [[round(float(x), 1), round(float(y), 1)] for x, y in user_kpts.tolist()],
                "kpts_conf": [round(float(c), 3) for c in user_conf.tolist()],
                "frame_w": int(frame.shape[1]),
                "frame_h": int(frame.shape[0]),
                "valid": bool(cmp.valid),
                "client_ts": client_ts,
            }
            await ws.send_json(response)

            # Ghi recorder
            if recorder is not None:
                # render skeleton lên user frame
                from pose_utils import draw_skeleton
                user_disp = frame.copy()
                draw_skeleton(user_disp, user_kpts, user_conf, joint_scores=cmp.per_joint)
                # ref frame: dùng đen nếu không có video src
                ref_disp = np.zeros((ref.height or 480, ref.width or 640, 3), dtype=np.uint8)
                draw_skeleton(ref_disp, ref_kpts, ref_conf, base_color=(220, 220, 220))
                recorder.write_frame(user_disp, ref_disp)
                recorder.add_entry(
                    frame_idx=frame_count, ref_frame_idx=ref_idx,
                    accuracy=cmp.overall, per_joint=cmp.per_joint,
                    feedback=fb, valid=cmp.valid,
                )

            prev_user = user_kpts.copy()
            prev_ref = ref_kpts.copy()
            frame_count += 1

    except WebSocketDisconnect:
        print("[ws] client disconnected")
    except Exception as e:  # noqa: BLE001
        print(f"[ws] error: {e}")
        try:
            await ws.send_json({"type": "error", "msg": str(e)})
        except Exception:
            pass
    finally:
        # Finalize recorder
        if recorder is not None:
            out_dir = recorder.close()
            session_name = out_dir.name
            print(f"[ws] session saved: {out_dir}")
            try:
                await ws.send_json({
                    "type": "session",
                    "session": session_name,
                    "report_url": f"/sessions/{session_name}/report.json",
                    "video_url": f"/sessions/{session_name}/side_by_side.mp4",
                    "num_frames": frame_count,
                })
            except Exception:
                pass
        try:
            await ws.close()
        except Exception:
            pass
        print(f"[ws] closed (frames processed: {frame_count})")


# ---------- Main ----------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # reload=True làm pose model load 2 lần, tốn RAM
    )
