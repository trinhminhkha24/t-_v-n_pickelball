// COCO-17 keypoint constants, ported từ motion-compare/pose_utils.py
// Giữ cùng index để tương thích với server response.

export const KP = {
  NOSE: 0,
  LEFT_EYE: 1,
  RIGHT_EYE: 2,
  LEFT_EAR: 3,
  RIGHT_EAR: 4,
  LEFT_SHOULDER: 5,
  RIGHT_SHOULDER: 6,
  LEFT_ELBOW: 7,
  RIGHT_ELBOW: 8,
  LEFT_WRIST: 9,
  RIGHT_WRIST: 10,
  LEFT_HIP: 11,
  RIGHT_HIP: 12,
  LEFT_KNEE: 13,
  RIGHT_KNEE: 14,
  LEFT_ANKLE: 15,
  RIGHT_ANKLE: 16,
} as const;

export const SKELETON_EDGES: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [0, 2], [1, 3], [2, 4],
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16],
];

export type JointGroup = { name: string; ids: number[] };

export const JOINT_GROUPS: JointGroup[] = [
  { name: 'Đầu', ids: [KP.NOSE, KP.LEFT_EYE, KP.RIGHT_EYE, KP.LEFT_EAR, KP.RIGHT_EAR] },
  { name: 'Vai', ids: [KP.LEFT_SHOULDER, KP.RIGHT_SHOULDER] },
  { name: 'Khuỷu tay', ids: [KP.LEFT_ELBOW, KP.RIGHT_ELBOW] },
  { name: 'Cổ tay', ids: [KP.LEFT_WRIST, KP.RIGHT_WRIST] },
  { name: 'Hông', ids: [KP.LEFT_HIP, KP.RIGHT_HIP] },
  { name: 'Đầu gối', ids: [KP.LEFT_KNEE, KP.RIGHT_KNEE] },
  { name: 'Cổ chân', ids: [KP.LEFT_ANKLE, KP.RIGHT_ANKLE] },
];

export const CONF_TH = 0.25;

/** Map accuracy score (0-100) -> màu hex. */
export function scoreToColor(score: number | null): string {
  if (score === null || Number.isNaN(score)) return '#888888';
  if (score >= 80) return '#3CDC3C'; // xanh lá
  if (score >= 50) return '#DCDC28'; // vàng
  return '#E63C3C'; // đỏ
}

/** Trung bình các giá trị không-null (cho per-joint group). */
export function avgValid(values: Array<number | null>): number | null {
  const xs = values.filter((v): v is number => v !== null && !Number.isNaN(v));
  if (xs.length === 0) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}
