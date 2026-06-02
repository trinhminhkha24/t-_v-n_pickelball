"""Pose utilities dùng chung cho module motion-compare.

- COCO-17 keypoint indices và tên.
- Skeleton edges (giống `yolo-tracking.py`).
- Hàm vẽ skeleton với màu theo per-joint accuracy.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


# COCO-17 keypoint indices
KP_NOSE = 0
KP_LEFT_EYE = 1
KP_RIGHT_EYE = 2
KP_LEFT_EAR = 3
KP_RIGHT_EAR = 4
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_ELBOW = 7
KP_RIGHT_ELBOW = 8
KP_LEFT_WRIST = 9
KP_RIGHT_WRIST = 10
KP_LEFT_HIP = 11
KP_RIGHT_HIP = 12
KP_LEFT_KNEE = 13
KP_RIGHT_KNEE = 14
KP_LEFT_ANKLE = 15
KP_RIGHT_ANKLE = 16


KP_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


# Tên tiếng Việt cho feedback
KP_NAMES_VI = [
    "mũi", "mắt trái", "mắt phải", "tai trái", "tai phải",
    "vai trái", "vai phải", "khuỷu tay trái", "khuỷu tay phải",
    "cổ tay trái", "cổ tay phải", "hông trái", "hông phải",
    "đầu gối trái", "đầu gối phải", "cổ chân trái", "cổ chân phải",
]


SKELETON_EDGES = [
    (0, 1), (0, 2), (1, 3), (2, 4),
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
]


# Nhóm joint dùng cho UI breakdown
JOINT_GROUPS = [
    ("Đầu",       [KP_NOSE, KP_LEFT_EYE, KP_RIGHT_EYE, KP_LEFT_EAR, KP_RIGHT_EAR]),
    ("Vai",       [KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER]),
    ("Khuỷu tay", [KP_LEFT_ELBOW, KP_RIGHT_ELBOW]),
    ("Cổ tay",    [KP_LEFT_WRIST, KP_RIGHT_WRIST]),
    ("Hông",      [KP_LEFT_HIP, KP_RIGHT_HIP]),
    ("Đầu gối",   [KP_LEFT_KNEE, KP_RIGHT_KNEE]),
    ("Cổ chân",   [KP_LEFT_ANKLE, KP_RIGHT_ANKLE]),
]


CONF_TH = 0.25  # ngưỡng confidence mặc định


def _as_int_tuple(xy):
    return int(round(float(xy[0]))), int(round(float(xy[1])))


def score_to_color(score: float) -> tuple[int, int, int]:
    """Map accuracy score (0-100) -> màu BGR.

    >=80: xanh lá; 50-80: vàng; <50: đỏ.
    """
    if score >= 80.0:
        return (60, 220, 60)
    if score >= 50.0:
        return (40, 220, 220)
    return (60, 60, 230)


def draw_skeleton(
    im: np.ndarray,
    kpts_xy: np.ndarray,
    kpts_conf: Optional[np.ndarray] = None,
    base_color: tuple[int, int, int] = (255, 255, 255),
    joint_scores: Optional[np.ndarray] = None,
    kpt_radius: int = 4,
    conf_th: float = CONF_TH,
) -> None:
    """Vẽ skeleton lên ảnh.

    Nếu có `joint_scores` (shape (17,)) thì mỗi joint được tô màu theo score.
    Ngược lại dùng `base_color`.
    """
    if kpts_xy is None or len(kpts_xy) == 0:
        return

    def ok(i: int) -> bool:
        if kpts_conf is None:
            return True
        return float(kpts_conf[i]) >= conf_th

    def color_for(i: int) -> tuple[int, int, int]:
        if joint_scores is not None and i < len(joint_scores):
            return score_to_color(float(joint_scores[i]))
        return base_color

    # Edges
    for a, b in SKELETON_EDGES:
        if ok(a) and ok(b):
            pa = _as_int_tuple((kpts_xy[a, 0], kpts_xy[a, 1]))
            pb = _as_int_tuple((kpts_xy[b, 0], kpts_xy[b, 1]))
            # màu cạnh = trung bình màu 2 đầu (đơn giản dùng đầu a)
            cv2.line(im, pa, pb, color_for(a), 2, cv2.LINE_AA)

    # Keypoints
    for i in range(kpts_xy.shape[0]):
        if ok(i):
            p = _as_int_tuple((kpts_xy[i, 0], kpts_xy[i, 1]))
            cv2.circle(im, p, kpt_radius, color_for(i), -1, cv2.LINE_AA)
            # viền đen để dễ nhìn trên nền sáng
            cv2.circle(im, p, kpt_radius, (0, 0, 0), 1, cv2.LINE_AA)


def pick_best_person(boxes_xyxy: np.ndarray, kpts_conf: Optional[np.ndarray]) -> int:
    """Chọn 1 người mỗi frame (tổng confidence keypoints cao nhất).

    Trả về index trong arrays; mặc định 0 nếu chỉ có 1 người.
    """
    if boxes_xyxy is None or len(boxes_xyxy) == 0:
        return -1
    if len(boxes_xyxy) == 1 or kpts_conf is None:
        return 0
    sums = kpts_conf.sum(axis=1)
    return int(np.argmax(sums))
