"""Lưu kết quả phiên so sánh.

- Side-by-side video: [user_annotated | reference_annotated].
- Report JSON: list các entry {frame, accuracy, per_joint, feedback}.
- Tự tạo session folder: motion-compare/sessions/<timestamp>/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"


class SessionRecorder:
    def __init__(
        self,
        session_dir: Optional[Path] = None,
        fps: float = 30.0,
        size: tuple[int, int] = (1280, 480),
    ) -> None:
        """size = (width, height) của video side-by-side đã ghép."""
        if session_dir is None:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            session_dir = SESSIONS_DIR / stamp
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.video_path = self.session_dir / "side_by_side.mp4"
        self.report_path = self.session_dir / "report.json"

        self.fps = float(fps)
        self.size = size  # (w, h)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(str(self.video_path), fourcc, self.fps, self.size)

        self.entries: list[dict] = []
        self.started_at = time.time()
        self.closed = False

    @staticmethod
    def make_side_by_side(left: np.ndarray, right: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
        """Ghép 2 frame thành 1 frame side-by-side với size cố định."""
        w, h = target_size
        half_w = w // 2
        l = cv2.resize(left, (half_w, h))
        r = cv2.resize(right, (w - half_w, h))
        return np.hstack([l, r])

    def write_frame(self, left: np.ndarray, right: np.ndarray) -> None:
        if self.closed:
            return
        frame = self.make_side_by_side(left, right, self.size)
        self.writer.write(frame)

    def add_entry(
        self,
        frame_idx: int,
        ref_frame_idx: int,
        accuracy: float,
        per_joint: np.ndarray,
        feedback: list[str],
        valid: bool,
    ) -> None:
        if self.closed:
            return
        per_joint_list = [None if np.isnan(v) else float(v) for v in per_joint.tolist()]
        self.entries.append({
            "frame": int(frame_idx),
            "ref_frame": int(ref_frame_idx),
            "accuracy": float(accuracy),
            "valid": bool(valid),
            "per_joint": per_joint_list,   # length 17, COCO order
            "feedback": list(feedback),
            "t": round(time.time() - self.started_at, 3),
        })

    def close(self) -> Path:
        if self.closed:
            return self.session_dir
        self.closed = True
        try:
            self.writer.release()
        except Exception:
            pass

        report = {
            "started_at": self.started_at,
            "duration_sec": round(time.time() - self.started_at, 3),
            "fps": self.fps,
            "video": self.video_path.name,
            "num_frames": len(self.entries),
            "avg_accuracy": (
                float(np.mean([e["accuracy"] for e in self.entries if e["valid"]]))
                if any(e["valid"] for e in self.entries) else 0.0
            ),
            "frames": self.entries,
        }
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return self.session_dir
