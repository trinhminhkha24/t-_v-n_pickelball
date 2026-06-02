"""Motion comparison engine.

Quy trình mỗi frame:
1) Normalize pose: hip-center về gốc, scale theo torso length (vai-hông).
2) Per-joint Euclidean distance giữa user và reference (đã normalize).
3) Per-joint velocity distance (đạo hàm theo frame, cũng đã normalize).
4) Map distance -> accuracy (0-100) bằng hàm exp-decay.
5) Overall = trung bình có trọng số confidence.

Joint nào conf user hoặc ref dưới ngưỡng -> coi như "không xác định",
KHÔNG đưa vào tổng accuracy nhưng vẫn được trả về để UI hiển thị "n/a".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pose_utils import (
    CONF_TH,
    KP_LEFT_HIP,
    KP_LEFT_SHOULDER,
    KP_RIGHT_HIP,
    KP_RIGHT_SHOULDER,
)


# ---------- Normalize ----------

def _safe_xy(kpts: np.ndarray, idx: int, conf: np.ndarray, th: float) -> Optional[np.ndarray]:
    if conf[idx] < th:
        return None
    return kpts[idx].astype(np.float32)


def normalize_pose(
    kpts: np.ndarray, conf: np.ndarray, conf_th: float = CONF_TH
) -> tuple[Optional[np.ndarray], Optional[float]]:
    """Đưa pose về toạ độ chuẩn:
       hip-center là gốc, scale = torso length (shoulder-mid -> hip-mid).

    Trả về (normalized_kpts (17,2), scale). Nếu thiếu các điểm cốt lõi -> (None, None).
    """
    lhip = _safe_xy(kpts, KP_LEFT_HIP, conf, conf_th)
    rhip = _safe_xy(kpts, KP_RIGHT_HIP, conf, conf_th)
    lsho = _safe_xy(kpts, KP_LEFT_SHOULDER, conf, conf_th)
    rsho = _safe_xy(kpts, KP_RIGHT_SHOULDER, conf, conf_th)

    # Hip center: trung điểm 2 hông; nếu thiếu 1 thì dùng cái còn lại; nếu thiếu cả -> dùng shoulder center; nếu vẫn thiếu -> fail.
    if lhip is not None and rhip is not None:
        hip_c = 0.5 * (lhip + rhip)
    elif lhip is not None:
        hip_c = lhip
    elif rhip is not None:
        hip_c = rhip
    elif lsho is not None and rsho is not None:
        hip_c = 0.5 * (lsho + rsho)
    else:
        return None, None

    # Shoulder center
    if lsho is not None and rsho is not None:
        sho_c = 0.5 * (lsho + rsho)
    elif lsho is not None:
        sho_c = lsho
    elif rsho is not None:
        sho_c = rsho
    else:
        sho_c = None

    if sho_c is not None:
        scale = float(np.linalg.norm(sho_c - hip_c))
    else:
        scale = 0.0

    # Fallback scale: dùng shoulder-width hoặc hip-width
    if scale < 1e-3:
        if lsho is not None and rsho is not None:
            scale = float(np.linalg.norm(lsho - rsho))
        elif lhip is not None and rhip is not None:
            scale = float(np.linalg.norm(lhip - rhip))

    if scale < 1e-3:
        return None, None

    norm = (kpts.astype(np.float32) - hip_c[None, :]) / scale
    return norm, scale


# ---------- Comparison ----------

@dataclass
class FrameComparison:
    overall: float                # 0-100
    per_joint: np.ndarray         # (17,) float, 0-100, NaN nếu n/a
    joint_offset: np.ndarray      # (17, 2) vector user - ref trong toạ độ pixel user
    valid: bool                   # có chuẩn hoá được pose không


# Map distance d (đã normalize theo torso length) -> điểm 0-100.
# d=0 -> 100; d=0.5 -> ~37; d=1.0 -> ~14. Decay nhanh để người dùng cảm nhận.
_DECAY_POS = 2.5
_DECAY_VEL = 4.0
_VEL_WEIGHT = 0.30   # tỷ trọng velocity term


def _score_from_distance(d: float, decay: float) -> float:
    return 100.0 * float(np.exp(-decay * d))


def compare_frame(
    user_kpts: np.ndarray, user_conf: np.ndarray,
    ref_kpts: np.ndarray, ref_conf: np.ndarray,
    prev_user_kpts: Optional[np.ndarray] = None,
    prev_ref_kpts: Optional[np.ndarray] = None,
    conf_th: float = CONF_TH,
) -> FrameComparison:
    """So sánh 1 frame của user với 1 frame của reference.

    `prev_*` (đã chuẩn hoá hoặc raw đều được - hàm sẽ chuẩn hoá lại) để tính velocity.
    Nếu None -> bỏ qua velocity term.
    """
    user_norm, _ = normalize_pose(user_kpts, user_conf, conf_th)
    ref_norm, _ = normalize_pose(ref_kpts, ref_conf, conf_th)

    if user_norm is None or ref_norm is None:
        return FrameComparison(
            overall=0.0,
            per_joint=np.full((17,), np.nan, dtype=np.float32),
            joint_offset=np.zeros((17, 2), dtype=np.float32),
            valid=False,
        )

    # Position distance per joint (normalized)
    pos_diff = user_norm - ref_norm                       # (17, 2)
    pos_dist = np.linalg.norm(pos_diff, axis=1)           # (17,)

    # Velocity distance (nếu có prev). Quan trọng: nếu không có prev hợp lệ,
    # KHÔNG trộn velocity vào score (tránh lạm phát điểm bằng s_vel=100 giả).
    vel_dist: np.ndarray | None = None
    if prev_user_kpts is not None and prev_ref_kpts is not None:
        # Chuẩn hoá prev theo chính nó (dùng conf hiện tại làm proxy cho ngưỡng).
        prev_un, _ = normalize_pose(prev_user_kpts, user_conf, conf_th)
        prev_rn, _ = normalize_pose(prev_ref_kpts, ref_conf, conf_th)
        if prev_un is not None and prev_rn is not None:
            v_user = user_norm - prev_un
            v_ref = ref_norm - prev_rn
            vel_dist = np.linalg.norm(v_user - v_ref, axis=1).astype(np.float32)

    # Per-joint score
    per_joint = np.full((17,), np.nan, dtype=np.float32)
    for i in range(17):
        if user_conf[i] < conf_th or ref_conf[i] < conf_th:
            continue
        s_pos = _score_from_distance(float(pos_dist[i]), _DECAY_POS)
        if vel_dist is not None:
            s_vel = _score_from_distance(float(vel_dist[i]), _DECAY_VEL)
            per_joint[i] = (1.0 - _VEL_WEIGHT) * s_pos + _VEL_WEIGHT * s_vel
        else:
            per_joint[i] = s_pos

    # Overall: trung bình các joint hợp lệ, có trọng số = min(user_conf, ref_conf)
    mask = ~np.isnan(per_joint)
    if not mask.any():
        overall = 0.0
    else:
        weights = np.minimum(user_conf, ref_conf)[mask]
        if weights.sum() < 1e-6:
            overall = float(np.nanmean(per_joint[mask]))
        else:
            overall = float(np.sum(per_joint[mask] * weights) / weights.sum())

    return FrameComparison(
        overall=overall,
        per_joint=per_joint,
        joint_offset=pos_diff.astype(np.float32),
        valid=True,
    )
