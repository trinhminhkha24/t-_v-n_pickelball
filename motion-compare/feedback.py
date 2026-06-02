"""Sinh feedback tiếng Việt cho người dùng.

Dựa vào:
- `per_joint` score (0-100, NaN nếu n/a) -> tìm joint sai nhất.
- `joint_offset` (user - ref) đã NORMALIZED theo torso length (đơn vị: torso).
  Sign: y dương = user ở dưới ref (cần nâng), x dương = user lệch sang phải khung
  hình so với ref (cần dịch sang trái).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pose_utils import KP_NAMES_VI


# Ngưỡng đánh giá: dưới 70 -> cần sửa
_NEEDS_FIX_TH = 70.0
# Ngưỡng offset (đơn vị torso) để xét là "đáng kể"
_MIN_OFFSET_NORM = 0.08  # ~8% torso length


def _direction_phrase(dx_n: float, dy_n: float) -> str:
    """Mô tả hướng cần sửa, dx_n và dy_n đã ở đơn vị torso (sau normalize)."""
    parts: list[str] = []
    # y: user thấp hơn ref (dy > 0) -> cần nâng lên
    if abs(dy_n) >= _MIN_OFFSET_NORM:
        parts.append("nâng cao hơn" if dy_n > 0 else "hạ thấp hơn")
    # x: user lệch sang phải so với ref (dx > 0) -> cần dịch sang trái
    if abs(dx_n) >= _MIN_OFFSET_NORM:
        parts.append("dịch sang trái" if dx_n > 0 else "dịch sang phải")

    if not parts:
        return "điều chỉnh nhẹ"
    return ", ".join(parts)


def generate_feedback(
    per_joint: np.ndarray,
    joint_offset: np.ndarray,
    torso_px: float = 0.0,   # giữ tham số cho tương thích; không dùng vì offset đã normalized
    top_k: int = 2,
) -> list[str]:
    """Trả về danh sách feedback tiếng Việt (tối đa top_k câu)."""
    del torso_px  # noqa: F841 - giữ tương thích chữ ký cũ
    msgs: list[str] = []
    if per_joint is None or len(per_joint) == 0:
        return msgs

    valid_idx = [i for i in range(len(per_joint)) if not np.isnan(per_joint[i])]
    bad = [(i, float(per_joint[i])) for i in valid_idx if per_joint[i] < _NEEDS_FIX_TH]
    if not bad:
        return ["Tư thế khớp tốt, giữ nguyên nhịp."]

    bad.sort(key=lambda t: t[1])  # thấp nhất trước

    for i, score in bad[:top_k]:
        name = KP_NAMES_VI[i] if i < len(KP_NAMES_VI) else f"joint {i}"
        direction = _direction_phrase(
            float(joint_offset[i, 0]), float(joint_offset[i, 1])
        )
        msgs.append(f"{name.capitalize()}: {direction} ({score:.0f}%).")

    return msgs


def estimate_torso_px(kpts: np.ndarray, conf: np.ndarray, conf_th: float = 0.25) -> float:
    """Ước lượng torso length theo pixel (dùng cho hiển thị nếu cần)."""
    from pose_utils import KP_LEFT_HIP, KP_LEFT_SHOULDER, KP_RIGHT_HIP, KP_RIGHT_SHOULDER

    def ok(i):
        return conf[i] >= conf_th

    if ok(KP_LEFT_SHOULDER) and ok(KP_RIGHT_SHOULDER) and ok(KP_LEFT_HIP) and ok(KP_RIGHT_HIP):
        sho = 0.5 * (kpts[KP_LEFT_SHOULDER] + kpts[KP_RIGHT_SHOULDER])
        hip = 0.5 * (kpts[KP_LEFT_HIP] + kpts[KP_RIGHT_HIP])
        return float(np.linalg.norm(sho - hip))
    if ok(KP_LEFT_SHOULDER) and ok(KP_RIGHT_SHOULDER):
        return float(np.linalg.norm(kpts[KP_LEFT_SHOULDER] - kpts[KP_RIGHT_SHOULDER]))
    return 0.0

