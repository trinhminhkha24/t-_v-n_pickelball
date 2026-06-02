"""Create a simple demo preset for Motion Compare.

This script writes a .npz file into motion-compare/presets/Forehand-Demo.npz
with synthetic keypoints so you can try the web client without video files.
"""
from pathlib import Path
import numpy as np

PRESETS = Path(__file__).resolve().parent / "presets"
PRESETS.mkdir(exist_ok=True)

name = "Forehand-Demo"
num_frames = 120
fps = 30.0
width = 640
height = 480

# Create synthetic keypoints: 17 joints, simple sinusoidal motion
kpts = np.zeros((num_frames, 17, 2), dtype=np.float32)
conf = np.ones((num_frames, 17), dtype=np.float32) * 0.9

for t in range(num_frames):
    phase = t / num_frames * 2 * np.pi
    for j in range(17):
        # distribute points across the frame with small oscillation
        x = (j + 1) * (width / 18.0) + 20.0 * np.sin(phase * (0.5 + j / 17.0))
        y = height / 2 + 40.0 * np.cos(phase * (0.4 + j / 17.0))
        kpts[t, j, 0] = float(x)
        kpts[t, j, 1] = float(y)

out_path = PRESETS / f"{name}.npz"
np.savez_compressed(
    out_path,
    name=np.array(name),
    kpts=kpts.astype(np.float32),
    conf=conf.astype(np.float32),
    fps=np.array(fps, dtype=np.float32),
    width=np.array(width, dtype=np.int32),
    height=np.array(height, dtype=np.int32),
    src_path=np.array("")
)
print(f"Wrote demo preset: {out_path}")
