"""CLI: build reference motion .npz từ 1 video.

Ví dụ:
    python motion-compare/build_reference.py --video input-videos/Forehand-Drive.mp4
    python motion-compare/build_reference.py --video my_squat.mp4 --name squat
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from reference import PRESETS_DIR, build_from_video


def main() -> None:
    parser = argparse.ArgumentParser(description="Build reference motion .npz từ video")
    parser.add_argument("--video", type=Path, required=True, help="Đường dẫn video mẫu")
    parser.add_argument("--name", type=str, default=None, help="Tên preset (mặc định = stem của file video)")
    parser.add_argument(
        "--pose-model",
        type=Path,
        default=_HERE.parent / "yolov8n-pose.pt",
        help="Đường dẫn YOLO pose model",
    )
    parser.add_argument("--output-dir", type=Path, default=PRESETS_DIR)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.7)
    args = parser.parse_args()

    # Lazy import để tránh import nặng khi chỉ --help
    from ultralytics import YOLO

    if not args.pose_model.exists():
        print(f"[!] Pose model không tồn tại: {args.pose_model}")
        sys.exit(2)

    pose = YOLO(str(args.pose_model))

    ref = build_from_video(
        video_path=args.video,
        pose_model=pose,
        name=args.name,
        conf_th=args.conf,
        iou_th=args.iou,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{ref.name}.npz"
    ref.save(out_path)
    print(f"[ok] Đã lưu preset: {out_path}")
    print(f"     frames={ref.num_frames}, fps={ref.fps:.2f}, size={ref.width}x{ref.height}")


if __name__ == "__main__":
    main()
