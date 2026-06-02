"""FastAPI server cho Motion Compare.

Endpoints:
    GET  /                 - health check + thông tin server
    GET  /presets          - list các preset .npz có sẵn
    GET  /presets/{name}   - metadata 1 preset (num_frames, fps, ...)
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
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Form, UploadFile, File, Cookie
import uuid
import time

# Tái dùng module motion-compare
_ROOT = Path(__file__).resolve().parent.parent
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

# Serve the web client if present inside the motion-compare package
WEB_DIR = _MC / "web"
if WEB_DIR.exists():
    try:
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    except Exception:
        pass
    @app.get("/web")
    def motion_compare_web():
        return FileResponse(WEB_DIR / "index.html")

# Simple in-memory session store for admin
app.state.sessions = {}
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "adminpass"  # change as needed or load from env

def create_session(role: str) -> str:
    token = str(uuid.uuid4())
    app.state.sessions[token] = {"role": role, "ts": time.time()}
    return token

def get_session(session_token: str | None):
    if not session_token:
        return None
    return app.state.sessions.get(session_token)

def require_admin(session_token: str | None):
    s = get_session(session_token)
    if not s or s.get("role") != "admin":
        return False
    return True


@app.get("/admin")
def admin_page():
    if WEB_DIR.exists() and (WEB_DIR / "admin.html").exists():
        return FileResponse(WEB_DIR / "admin.html")
    return JSONResponse({"error": "admin UI not installed"}, status_code=404)


@app.post("/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = create_session("admin")
        resp = JSONResponse({"ok": True, "role": "admin"})
        resp.set_cookie("mc_session", token, httponly=True)
        return resp
    return JSONResponse({"ok": False, "msg": "invalid credentials"}, status_code=401)


@app.post("/admin/logout")
def admin_logout(mc_session: str | None = Cookie(default=None)):
    if mc_session and mc_session in app.state.sessions:
        del app.state.sessions[mc_session]
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("mc_session")
    return resp


@app.get("/admin/api/presets")
def admin_list_presets(mc_session: str | None = Cookie(default=None)):
    if not require_admin(mc_session):
        return JSONResponse({"ok": False, "msg": "unauthorized"}, status_code=401)
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
            })
        except Exception as e:
            out.append({"name": p.stem, "error": str(e)})
    return {"ok": True, "presets": out}


@app.post("/admin/api/delete_preset")
def admin_delete_preset(name: str = Form(...), mc_session: str | None = Cookie(default=None)):
    if not require_admin(mc_session):
        return JSONResponse({"ok": False, "msg": "unauthorized"}, status_code=401)
    path = PRESETS_DIR / f"{name}.npz"
    if path.exists():
        path.unlink()
        return {"ok": True}
    return JSONResponse({"ok": False, "msg": "not found"}, status_code=404)


@app.post("/admin/api/upload_preset")
def admin_upload_preset(file: UploadFile = File(...), mc_session: str | None = Cookie(default=None)):
    if not require_admin(mc_session):
        return JSONResponse({"ok": False, "msg": "unauthorized"}, status_code=401)
    # Expect a .npz file uploaded
    if not file.filename.endswith('.npz'):
        return JSONResponse({"ok": False, "msg": "invalid file"}, status_code=400)
    dest = PRESETS_DIR / file.filename
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    with open(dest, 'wb') as f:
        f.write(file.file.read())
    return {"ok": True, "name": file.filename}

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
