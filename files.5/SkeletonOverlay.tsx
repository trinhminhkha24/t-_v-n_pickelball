import React from 'react';
import Svg, { Circle, Line } from 'react-native-svg';
import { SKELETON_EDGES, CONF_TH, scoreToColor } from '../lib/coco';

type Props = {
  /** keypoints toạ độ trong hệ ảnh gốc của server (frame_w x frame_h) */
  kpts: Array<[number, number]>;
  kptsConf: number[];
  /** per-joint score (0-100 hoặc null) để tô màu */
  perJoint: Array<number | null>;
  /** kích thước ảnh gốc (server trả) */
  frameW: number;
  frameH: number;
  /** kích thước canvas hiển thị trên màn hình */
  viewW: number;
  viewH: number;
  /** lật ngang (cho camera trước thường đã mirror sẵn ở RN) */
  mirror?: boolean;
};

/** Vẽ skeleton lên 1 lớp SVG trùng kích thước view camera. */
export const SkeletonOverlay: React.FC<Props> = ({
  kpts, kptsConf, perJoint, frameW, frameH, viewW, viewH, mirror = false,
}) => {
  if (!kpts || kpts.length === 0 || frameW <= 0 || frameH <= 0) return null;

  // Map toạ độ ảnh -> toạ độ view (giả sử view scale uniform "cover")
  // dùng object-fit: cover -> scale = max(viewW/frameW, viewH/frameH)
  const scale = Math.max(viewW / frameW, viewH / frameH);
  const offsetX = (viewW - frameW * scale) / 2;
  const offsetY = (viewH - frameH * scale) / 2;

  const proj = (x: number, y: number): [number, number] => {
    let px = x * scale + offsetX;
    if (mirror) px = viewW - px;
    const py = y * scale + offsetY;
    return [px, py];
  };

  const ok = (i: number) => (kptsConf[i] ?? 0) >= CONF_TH;
  const colorFor = (i: number) => scoreToColor(perJoint[i] ?? null);

  return (
    <Svg
      width={viewW}
      height={viewH}
      style={{ position: 'absolute', top: 0, left: 0 }}
      pointerEvents="none"
    >
      {SKELETON_EDGES.map(([a, b], idx) => {
        if (!ok(a) || !ok(b)) return null;
        const [ax, ay] = proj(kpts[a][0], kpts[a][1]);
        const [bx, by] = proj(kpts[b][0], kpts[b][1]);
        return (
          <Line
            key={`e${idx}`}
            x1={ax} y1={ay} x2={bx} y2={by}
            stroke={colorFor(a)}
            strokeWidth={3}
            strokeLinecap="round"
          />
        );
      })}
      {kpts.map((_, i) => {
        if (!ok(i)) return null;
        const [x, y] = proj(kpts[i][0], kpts[i][1]);
        return (
          <Circle
            key={`k${i}`}
            cx={x} cy={y} r={5}
            fill={colorFor(i)}
            stroke="black"
            strokeWidth={1}
          />
        );
      })}
    </Svg>
  );
};
