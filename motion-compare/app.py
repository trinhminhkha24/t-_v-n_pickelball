"""Motion Compare App - UI Tkinter 2 pane.

Left:  webcam realtime + skeleton overlay (màu theo per-joint accuracy).
Right: progress, overall accuracy, per-joint breakdown, feedback.

Cách chạy:
    python motion-compare/app.py
    python motion-compare/app.py --preset Forehand-Drive

Phím tắt:
    Space  -> Start/Stop
    M      -> Toggle gương webcam
    Esc    -> Đóng app
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import (
    BOTH, DISABLED, END, LEFT, NORMAL, RIGHT, TOP, W, X, Y,
    BooleanVar, Canvas, Checkbutton, Frame, IntVar, Label, OptionMenu,
    StringVar, Text, Tk, filedialog, messagebox, ttk,
)

import cv2
import numpy as np
from PIL import Image, ImageTk

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from comparator import compare_frame
from feedback import estimate_torso_px, generate_feedback
from pose_utils import (
    CONF_TH, JOINT_GROUPS, draw_skeleton, pick_best_person, score_to_color,
)
from recorder import SessionRecorder
from reference import PRESETS_DIR, ReferenceMotion, build_from_video


DEFAULT_POSE_MODEL = _HERE.parent / "yolov8n-pose.pt"


# ============== Worker (background thread) ==============

class CompareWorker(threading.Thread):
    """Thread chạy nền: capture webcam + đọc ref + chạy pose + so sánh.
    Đẩy kết quả vào queue cho UI thread render."""

    def __init__(
        self,
        pose_model_path: Path,
        ref: ReferenceMotion,
        out_queue: "queue.Queue",
        cam_index: int = 0,
        mirror: bool = False,
        loop: bool = False,
        recorder: SessionRecorder | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.pose_model_path = pose_model_path
        self.ref = ref
        self.q = out_queue
        self.cam_index = cam_index
        self.mirror = mirror
        self.loop = loop
        self.recorder = recorder
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as e:  # noqa: BLE001
            self.q.put({"type": "error", "msg": str(e)})
            self.q.put({"type": "stopped"})

    def _run_inner(self) -> None:
        from ultralytics import YOLO

        pose = YOLO(str(self.pose_model_path))

        cap = cv2.VideoCapture(self.cam_index)
        if not cap.isOpened():
            raise RuntimeError(f"Không mở được webcam (index={self.cam_index})")
        cap.set(cv2.CAP_PROP_FPS, 30)

        # Reference video (nếu còn) để hiển thị
        ref_cap: cv2.VideoCapture | None = None
        if self.ref.src_path and Path(self.ref.src_path).exists():
            ref_cap = cv2.VideoCapture(self.ref.src_path)

        ref_fps = self.ref.fps if self.ref.fps > 0 else 30.0
        num_ref = self.ref.num_frames

        prev_user: np.ndarray | None = None
        prev_ref: np.ndarray | None = None
        t0 = time.time()
        frame_idx = 0
        last_ref_idx_read = -1
        ref_frame_cache: np.ndarray | None = None

        fps_window: list[float] = []
        last_t = time.time()

        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            now = time.time()
            elapsed = now - t0

            # Ref index theo thời gian thực
            target_ref_idx = int(elapsed * ref_fps)
            if target_ref_idx >= num_ref:
                if self.loop:
                    t0 = now
                    target_ref_idx = 0
                    last_ref_idx_read = -1
                    if ref_cap is not None:
                        ref_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    target_ref_idx = num_ref - 1
                    if frame_idx > num_ref + 5:
                        self.q.put({"type": "done"})
                        break
            target_ref_idx = max(0, min(num_ref - 1, target_ref_idx))

            # Đọc ref frame (ưu tiên linear forward, seek nếu lùi)
            if ref_cap is not None and target_ref_idx != last_ref_idx_read:
                if target_ref_idx < last_ref_idx_read:
                    ref_cap.set(cv2.CAP_PROP_POS_FRAMES, target_ref_idx)
                else:
                    while last_ref_idx_read + 1 < target_ref_idx:
                        ref_cap.grab()
                        last_ref_idx_read += 1
                ok_ref, ref_img = ref_cap.read()
                if ok_ref:
                    ref_frame_cache = ref_img
                    last_ref_idx_read = target_ref_idx

            # Mirror webcam (cả ảnh hiển thị + keypoints nhờ flip ảnh trước inference)
            if self.mirror:
                frame = cv2.flip(frame, 1)

            # Pose trên webcam
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

            ref_kpts = self.ref.kpts[target_ref_idx]
            ref_conf = self.ref.conf[target_ref_idx]

            # So sánh
            cmp = compare_frame(
                user_kpts, user_conf,
                ref_kpts, ref_conf,
                prev_user_kpts=prev_user,
                prev_ref_kpts=prev_ref,
            )

            torso = estimate_torso_px(user_kpts, user_conf)
            fb_msgs = generate_feedback(cmp.per_joint, cmp.joint_offset, torso)

            # Render: webcam + skeleton màu theo joint score
            disp = frame.copy()
            draw_skeleton(disp, user_kpts, user_conf, joint_scores=cmp.per_joint)
            # Overlay nhỏ trên webcam: overall + fps
            _overlay_hud(disp, cmp.overall, frame_idx, target_ref_idx, num_ref)

            # Render: reference frame + skeleton trắng
            if ref_frame_cache is not None:
                ref_disp = ref_frame_cache.copy()
            else:
                ref_disp = np.zeros((self.ref.height or 480, self.ref.width or 640, 3), dtype=np.uint8)
            draw_skeleton(ref_disp, ref_kpts, ref_conf, base_color=(220, 220, 220))

            # FPS
            dt = now - last_t
            last_t = now
            if dt > 0:
                fps_window.append(1.0 / dt)
                if len(fps_window) > 30:
                    fps_window.pop(0)
            fps_avg = sum(fps_window) / len(fps_window) if fps_window else 0.0

            self.q.put({
                "type": "frame",
                "frame_idx": frame_idx,
                "ref_idx": target_ref_idx,
                "num_ref": num_ref,
                "fps": fps_avg,
                "user_img": disp,
                "ref_img": ref_disp,
                "overall": cmp.overall,
                "per_joint": cmp.per_joint.copy(),
                "valid": cmp.valid,
                "feedback": list(fb_msgs),
            })

            if self.recorder is not None:
                self.recorder.write_frame(disp, ref_disp)
                self.recorder.add_entry(
                    frame_idx=frame_idx, ref_frame_idx=target_ref_idx,
                    accuracy=cmp.overall, per_joint=cmp.per_joint,
                    feedback=fb_msgs, valid=cmp.valid,
                )

            prev_user = user_kpts.copy()
            prev_ref = ref_kpts.copy()
            frame_idx += 1

        cap.release()
        if ref_cap is not None:
            ref_cap.release()
        self.q.put({"type": "stopped"})


def _overlay_hud(img: np.ndarray, overall: float, fidx: int, ridx: int, num_ref: int) -> None:
    h, w = img.shape[:2]
    txt1 = f"Accuracy: {overall:5.1f}%"
    txt2 = f"User f#{fidx}  Ref f#{ridx}/{num_ref}"
    # Panel mờ ở góc trên-trái
    pad = 8
    cv2.rectangle(img, (0, 0), (270, 56), (0, 0, 0), -1)
    cv2.putText(img, txt1, (pad, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, score_to_color(overall), 2, cv2.LINE_AA)
    cv2.putText(img, txt2, (pad, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)


# ============== UI ==============

class MotionCompareApp:
    def __init__(self, root: Tk, pose_model_path: Path, initial_ref: ReferenceMotion | None = None) -> None:
        self.root = root
        self.pose_model_path = pose_model_path
        self.ref: ReferenceMotion | None = initial_ref
        self.worker: CompareWorker | None = None
        self.recorder: SessionRecorder | None = None
        self.q: "queue.Queue" = queue.Queue(maxsize=4)
        self._photo: ImageTk.PhotoImage | None = None

        root.title("Motion Compare - Pickleball")
        root.geometry("1280x720")
        root.minsize(960, 600)

        self._build_ui()
        self._refresh_preset_list()
        if initial_ref is not None:
            self._update_ref_status()

        # Phím tắt
        root.bind("<space>", lambda e: self._toggle_start_stop())
        root.bind("m", lambda e: self.mirror_var.set(not self.mirror_var.get()))
        root.bind("<Escape>", lambda e: self._on_close())
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.root.after(33, self._poll_queue)

    # ----- UI construction -----
    def _build_ui(self) -> None:
        toolbar = Frame(self.root, padx=8, pady=6)
        toolbar.pack(side=TOP, fill=X)

        Label(toolbar, text="Preset:").pack(side=LEFT)
        self.preset_var = StringVar(value="(chưa có)")
        self.preset_menu = OptionMenu(toolbar, self.preset_var, "(chưa có)")
        self.preset_menu.pack(side=LEFT, padx=(4, 8))

        ttk.Button(toolbar, text="Load preset", command=self.on_load_preset).pack(side=LEFT)
        ttk.Button(toolbar, text="Mở video ref...", command=self.on_open_video).pack(side=LEFT, padx=(6, 6))

        self.mirror_var = BooleanVar(value=False)
        Checkbutton(toolbar, text="Gương webcam", variable=self.mirror_var).pack(side=LEFT, padx=(8, 0))
        self.loop_var = BooleanVar(value=False)
        Checkbutton(toolbar, text="Loop ref", variable=self.loop_var).pack(side=LEFT)
        self.record_var = BooleanVar(value=True)
        Checkbutton(toolbar, text="Lưu video + JSON", variable=self.record_var).pack(side=LEFT)

        self.start_btn = ttk.Button(toolbar, text="▶ Start", command=self.on_start)
        self.start_btn.pack(side=LEFT, padx=(10, 4))
        self.stop_btn = ttk.Button(toolbar, text="■ Stop", command=self.on_stop, state=DISABLED)
        self.stop_btn.pack(side=LEFT)

        self.status_var = StringVar(value="Sẵn sàng. (Space để Start/Stop)")
        Label(toolbar, textvariable=self.status_var, anchor=W).pack(side=LEFT, fill=X, expand=True, padx=10)

        # Main: 2 cột
        main = Frame(self.root)
        main.pack(side=TOP, fill=BOTH, expand=True)

        # ----- Left: webcam -----
        left = Frame(main, bg="#111")
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(8, 4), pady=4)
        self.video_canvas = Canvas(left, bg="#111", highlightthickness=0)
        self.video_canvas.pack(fill=BOTH, expand=True)

        self.info_var = StringVar(value="FPS: --   Frame: --")
        Label(left, textvariable=self.info_var, fg="white", bg="#111", anchor=W).pack(fill=X)

        # ----- Right: scoreboard -----
        right = Frame(main, width=420)
        right.pack(side=RIGHT, fill=Y, padx=(4, 8), pady=4)
        right.pack_propagate(False)

        Label(right, text="Tiến độ reference", anchor=W).pack(fill=X, pady=(0, 2))
        self.progress_var = IntVar(value=0)
        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100, variable=self.progress_var)
        self.progress.pack(fill=X)
        self.progress_text = StringVar(value="0 / 0")
        Label(right, textvariable=self.progress_text, anchor=W).pack(fill=X, pady=(0, 8))

        Label(right, text="Overall accuracy", anchor=W, font=("TkDefaultFont", 10, "bold")).pack(fill=X)
        self.overall_var = StringVar(value="--")
        self.overall_lbl = Label(right, textvariable=self.overall_var, font=("TkDefaultFont", 32, "bold"))
        self.overall_lbl.pack(fill=X, pady=(0, 8))

        Label(right, text="Per-joint breakdown", anchor=W, font=("TkDefaultFont", 10, "bold")).pack(fill=X)
        self.joint_frame = Frame(right)
        self.joint_frame.pack(fill=X, pady=(2, 8))
        self._joint_rows: list[tuple[ttk.Progressbar, StringVar]] = []
        for name, _ in JOINT_GROUPS:
            row = Frame(self.joint_frame)
            row.pack(fill=X, pady=1)
            Label(row, text=name, width=10, anchor=W).pack(side=LEFT)
            pb = ttk.Progressbar(row, mode="determinate", maximum=100, length=180)
            pb.pack(side=LEFT, padx=(2, 6))
            v = StringVar(value="--")
            Label(row, textvariable=v, width=6, anchor=W).pack(side=LEFT)
            self._joint_rows.append((pb, v))

        Label(right, text="Feedback", anchor=W, font=("TkDefaultFont", 10, "bold")).pack(fill=X)
        self.feedback_box = Text(right, height=6, wrap="word", state="disabled")
        self.feedback_box.pack(fill=BOTH, expand=True)

    # ----- Preset management -----
    def _refresh_preset_list(self) -> None:
        presets = ReferenceMotion.list_presets()
        menu = self.preset_menu["menu"]
        menu.delete(0, END)
        if not presets:
            self.preset_var.set("(chưa có)")
            menu.add_command(label="(chưa có)", command=lambda: None)
            return
        for p in presets:
            menu.add_command(label=p.stem, command=lambda v=p.stem: self.preset_var.set(v))
        if self.ref is not None:
            self.preset_var.set(self.ref.name)
        else:
            self.preset_var.set(presets[0].stem)

    def _update_ref_status(self) -> None:
        if self.ref is None:
            return
        self.progress_text.set(f"0 / {self.ref.num_frames}")
        self.status_var.set(
            f"Ref '{self.ref.name}': {self.ref.num_frames} frames @ {self.ref.fps:.1f} fps. (Space để Start)"
        )

    def on_load_preset(self) -> None:
        name = self.preset_var.get()
        if not name or name.startswith("("):
            messagebox.showinfo(
                "Preset",
                "Chưa có preset. Hãy 'Mở video ref...' hoặc chạy:\n"
                "  python motion-compare/build_reference.py --video <path>",
            )
            return
        path = PRESETS_DIR / f"{name}.npz"
        if not path.exists():
            messagebox.showerror("Preset", f"Không tìm thấy: {path}")
            return
        try:
            self.ref = ReferenceMotion.load(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Preset", f"Lỗi đọc preset: {e}")
            return
        self._update_ref_status()

    def on_open_video(self) -> None:
        fpath = filedialog.askopenfilename(
            title="Chọn video reference",
            filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv"), ("All", "*.*")],
        )
        if not fpath:
            return
        self.status_var.set("Đang trích keypoints từ video... (chờ chút)")
        self.root.update_idletasks()
        try:
            from ultralytics import YOLO
            pose = YOLO(str(self.pose_model_path))
            self.ref = build_from_video(Path(fpath), pose_model=pose)
            PRESETS_DIR.mkdir(parents=True, exist_ok=True)
            self.ref.save(PRESETS_DIR / f"{self.ref.name}.npz")
            self._refresh_preset_list()
            self._update_ref_status()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Build ref", str(e))
            self.status_var.set("Lỗi build ref.")

    # ----- Start / Stop -----
    def _toggle_start_stop(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.on_stop()
        else:
            self.on_start()

    def on_start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        if self.ref is None:
            self.on_load_preset()
            if self.ref is None:
                return

        self.recorder = (
            SessionRecorder(fps=max(10.0, self.ref.fps), size=(1280, 480))
            if self.record_var.get() else None
        )

        self.worker = CompareWorker(
            pose_model_path=self.pose_model_path,
            ref=self.ref,
            out_queue=self.q,
            cam_index=0,
            mirror=self.mirror_var.get(),
            loop=self.loop_var.get(),
            recorder=self.recorder,
        )
        self.worker.start()

        self.start_btn.config(state=DISABLED)
        self.stop_btn.config(state=NORMAL)
        self.status_var.set("Đang chạy... (Space để Stop)")

    def on_stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.status_var.set("Đang dừng...")

    # ----- Poll queue + UI updates -----
    def _poll_queue(self) -> None:
        latest_frame_msg: dict | None = None
        try:
            while True:
                msg = self.q.get_nowait()
                if msg.get("type") == "frame":
                    # giữ frame mới nhất, bỏ frame cũ để UI không lag
                    latest_frame_msg = msg
                else:
                    self._handle_msg(msg)
        except queue.Empty:
            pass
        if latest_frame_msg is not None:
            self._update_frame(latest_frame_msg)
        self.root.after(33, self._poll_queue)

    def _handle_msg(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "done":
            self.status_var.set("Đã hết reference. Đang dừng...")
            if self.worker is not None:
                self.worker.stop()
        elif kind == "stopped":
            self._finalize_session()
        elif kind == "error":
            messagebox.showerror("Lỗi worker", msg.get("msg", ""))

    def _finalize_session(self) -> None:
        out_dir = None
        if self.recorder is not None:
            out_dir = self.recorder.close()
        self.recorder = None
        self.worker = None
        self.start_btn.config(state=NORMAL)
        self.stop_btn.config(state=DISABLED)
        if out_dir is not None:
            self.status_var.set(f"Đã lưu phiên: {out_dir}")
        else:
            self.status_var.set("Đã dừng.")

    def _update_frame(self, msg: dict) -> None:
        img = msg["user_img"]
        cw = max(self.video_canvas.winfo_width(), 320)
        ch = max(self.video_canvas.winfo_height(), 240)
        h, w = img.shape[:2]
        s = min(cw / w, ch / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        img_resized = cv2.resize(img, (nw, nh))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        self._photo = ImageTk.PhotoImage(pil_img)
        self.video_canvas.delete("all")
        self.video_canvas.create_image(cw // 2, ch // 2, image=self._photo)

        self.info_var.set(
            f"FPS: {msg['fps']:.1f}   User f#{msg['frame_idx']}   Ref f#{msg['ref_idx']}/{msg['num_ref']}"
        )

        # Progress + overall
        num_ref = max(1, msg["num_ref"])
        self.progress_var.set(int(100 * msg["ref_idx"] / num_ref))
        self.progress_text.set(f"{msg['ref_idx']} / {num_ref}")

        if msg["valid"]:
            overall = msg["overall"]
            self.overall_var.set(f"{overall:.1f}%")
            bgr = score_to_color(overall)
            self.overall_lbl.config(fg=_bgr_to_hex(bgr))
        else:
            self.overall_var.set("n/a")
            self.overall_lbl.config(fg="#888888")

        # Per-joint
        per_joint = msg["per_joint"]
        for (name, ids), (pb, v) in zip(JOINT_GROUPS, self._joint_rows):
            vals = [per_joint[i] for i in ids if not np.isnan(per_joint[i])]
            if not vals:
                pb["value"] = 0
                v.set("--")
                continue
            avg = float(np.mean(vals))
            pb["value"] = int(avg)
            v.set(f"{avg:.0f}%")

        # Feedback
        fb = msg["feedback"]
        self.feedback_box.config(state=NORMAL)
        self.feedback_box.delete("1.0", END)
        if fb:
            for line in fb:
                self.feedback_box.insert(END, f"• {line}\n")
        self.feedback_box.config(state=DISABLED)

    # ----- Close -----
    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
            try:
                self.worker.join(timeout=2.0)
            except Exception:
                pass
        if self.recorder is not None:
            try:
                self.recorder.close()
            except Exception:
                pass
        self.root.destroy()


def _bgr_to_hex(bgr: tuple[int, int, int]) -> str:
    b, g, r = bgr
    return f"#{r:02x}{g:02x}{b:02x}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Motion Compare App")
    parser.add_argument("--pose-model", type=Path, default=DEFAULT_POSE_MODEL)
    parser.add_argument("--preset", type=str, default=None, help="Tên preset (file .npz, không cần đuôi)")
    parser.add_argument("--ref-video", type=Path, default=None, help="Build ref từ video này khi khởi động")
    args = parser.parse_args()

    if not args.pose_model.exists():
        print(f"[!] Không tìm thấy pose model: {args.pose_model}")
        sys.exit(2)

    initial_ref: ReferenceMotion | None = None
    if args.preset:
        p = PRESETS_DIR / f"{args.preset}.npz"
        if p.exists():
            initial_ref = ReferenceMotion.load(p)
        else:
            print(f"[!] Preset không tồn tại: {p}")
    elif args.ref_video is not None:
        from ultralytics import YOLO
        pose = YOLO(str(args.pose_model))
        initial_ref = build_from_video(args.ref_video, pose_model=pose)
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        initial_ref.save(PRESETS_DIR / f"{initial_ref.name}.npz")

    root = Tk()
    MotionCompareApp(root, pose_model_path=args.pose_model, initial_ref=initial_ref)
    root.mainloop()


if __name__ == "__main__":
    main()
