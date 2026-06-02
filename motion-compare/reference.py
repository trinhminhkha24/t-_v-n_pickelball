"""Reference motion template.

- Extract pose keypoints sequence từ 1 video mẫu bằng YOLOv8 pose.
- Lưu/đọc dạng .npz: kpts (N,17,2), conf (N,17), fps, width, height, src_path.
- Hỗ trợ load preset từ thư mục `presets/`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pose_utils import pick_best_person


PRESETS_DIR = _HERE / "presets"


@dataclass
class ReferenceMotion:
    """Một chuỗi pose mẫu để so sánh với người dùng."""

    name: str
    kpts: np.ndarray          # (N, 17, 2) float32, pixel coords
    conf: np.ndarray          # (N, 17)    float32, [0,1]
    fps: float
    width: int
    height: int
    src_path: str = ""        # đường dẫn video gốc (nếu còn tồn tại, dùng để hiển thị)

    @property
    def num_frames(self) -> int:
        return int(self.kpts.shape[0])

    @property
    def duration(self) -> float:
        if self.fps <= 0:
            return 0.0
        return self.num_frames / self.fps

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            name=np.array(self.name),
            kpts=self.kpts.astype(np.float32),
            conf=self.conf.astype(np.float32),
            fps=np.array(self.fps, dtype=np.float32),
            width=np.array(self.width, dtype=np.int32),
            height=np.array(self.height, dtype=np.int32),
            src_path=np.array(self.src_path),
        )

    @classmethod
    def load(cls, path: Path) -> "ReferenceMotion":
        path = Path(path)
        data = np.load(path, allow_pickle=False)
        return cls(
            name=str(data["name"]),
            kpts=data["kpts"].astype(np.float32),
            conf=data["conf"].astype(np.float32),
            fps=float(data["fps"]),
            width=int(data["width"]),
            height=int(data["height"]),
            src_path=str(data["src_path"]) if "src_path" in data.files else "",
        )

    @classmethod
    def list_presets(cls) -> list[Path]:
        """Liệt kê các file .npz preset có sẵn."""
        if not PRESETS_DIR.exists():
            return []
        return sorted(PRESETS_DIR.glob("*.npz"))


def build_from_video(
    video_path: Path,
    pose_model,
    name: Optional[str] = None,
    conf_th: float = 0.25,
    iou_th: float = 0.7,
    progress: bool = True,
) -> ReferenceMotion:
    """Đọc video, chạy pose model qua từng frame, gom keypoints sequence.

    Chọn 1 người duy nhất mỗi frame (highest total keypoint confidence).
    Khi không phát hiện người: dùng frame trước (carry forward) với conf=0.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[ref] {video_path.name}: {width}x{height} @ {fps:.1f} fps, {total} frames")

    kpts_seq: list[np.ndarray] = []
    conf_seq: list[np.ndarray] = []
    last_kpts = np.zeros((17, 2), dtype=np.float32)
    last_conf = np.zeros((17,), dtype=np.float32)

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        res = pose_model.predict(frame, conf=conf_th, iou=iou_th, verbose=False)

        if not res or res[0].keypoints is None or res[0].boxes is None:
            kpts_seq.append(last_kpts.copy())
            conf_seq.append(np.zeros((17,), dtype=np.float32))
            continue

        boxes_xyxy = res[0].boxes.xyxy.cpu().numpy()
        kxy = res[0].keypoints.xy.cpu().numpy()           # (P, 17, 2)
        kcf = (
            res[0].keypoints.conf.cpu().numpy()
            if res[0].keypoints.conf is not None
            else np.ones(kxy.shape[:2], dtype=np.float32)
        )

        idx = pick_best_person(boxes_xyxy, kcf)
        if idx < 0:
            kpts_seq.append(last_kpts.copy())
            conf_seq.append(np.zeros((17,), dtype=np.float32))
            continue

        last_kpts = kxy[idx].astype(np.float32)
        last_conf = kcf[idx].astype(np.float32)
        kpts_seq.append(last_kpts.copy())
        conf_seq.append(last_conf.copy())

        if progress and total > 0 and frame_idx % max(1, total // 10) == 0:
            pct = 100.0 * frame_idx / total
            print(f"  [ref] {pct:.1f}% ({frame_idx}/{total})")

    cap.release()

    kpts_arr = np.stack(kpts_seq, axis=0) if kpts_seq else np.zeros((0, 17, 2), dtype=np.float32)
    conf_arr = np.stack(conf_seq, axis=0) if conf_seq else np.zeros((0, 17), dtype=np.float32)

    if name is None:
        name = video_path.stem

    print(f"[ref] Built: {name} -> {kpts_arr.shape[0]} frames")
    return ReferenceMotion(
        name=name,
        kpts=kpts_arr,
        conf=conf_arr,
        fps=fps,
        width=width,
        height=height,
        src_path=str(video_path.resolve()),
    )
