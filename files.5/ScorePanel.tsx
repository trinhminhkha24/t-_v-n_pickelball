import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { JOINT_GROUPS, avgValid, scoreToColor } from '../lib/coco';

type Props = {
  refIdx: number;
  numRef: number;
  overall: number;
  perJoint: Array<number | null>;
  feedback: string[];
  valid: boolean;
  fps: number;
};

export const ScorePanel: React.FC<Props> = ({
  refIdx, numRef, overall, perJoint, feedback, valid, fps,
}) => {
  const progressPct = numRef > 0 ? Math.round((100 * refIdx) / numRef) : 0;
  const overallColor = valid ? scoreToColor(overall) : '#888';

  return (
    <ScrollView style={styles.panel} contentContainerStyle={{ paddingBottom: 16 }}>
      <Text style={styles.label}>Tiến độ reference</Text>
      <View style={styles.progressBg}>
        <View style={[styles.progressFg, { width: `${progressPct}%` }]} />
      </View>
      <Text style={styles.dim}>{refIdx} / {numRef}  ·  FPS: {fps.toFixed(1)}</Text>

      <Text style={[styles.label, { marginTop: 12 }]}>Overall accuracy</Text>
      <Text style={[styles.bigScore, { color: overallColor }]}>
        {valid ? `${overall.toFixed(1)}%` : 'n/a'}
      </Text>

      <Text style={[styles.label, { marginTop: 8 }]}>Per-joint</Text>
      {JOINT_GROUPS.map((grp) => {
        const vals = grp.ids.map((i) => perJoint[i] ?? null);
        const avg = avgValid(vals);
        const w = avg === null ? 0 : Math.max(0, Math.min(100, avg));
        const color = scoreToColor(avg);
        return (
          <View key={grp.name} style={styles.jointRow}>
            <Text style={styles.jointName}>{grp.name}</Text>
            <View style={styles.jointBarBg}>
              <View style={[styles.jointBarFg, { width: `${w}%`, backgroundColor: color }]} />
            </View>
            <Text style={[styles.jointVal, { color }]}>
              {avg === null ? '--' : `${avg.toFixed(0)}%`}
            </Text>
          </View>
        );
      })}

      <Text style={[styles.label, { marginTop: 12 }]}>Feedback</Text>
      <View style={styles.feedbackBox}>
        {feedback.length === 0 ? (
          <Text style={styles.dim}>—</Text>
        ) : (
          feedback.map((line, i) => (
            <Text key={i} style={styles.feedbackLine}>• {line}</Text>
          ))
        )}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  panel: { flex: 1, padding: 12, backgroundColor: '#fafafa' },
  label: { fontWeight: '600', fontSize: 12, color: '#333', marginBottom: 4 },
  dim: { fontSize: 11, color: '#666' },
  progressBg: { height: 8, backgroundColor: '#e0e0e0', borderRadius: 4, overflow: 'hidden' },
  progressFg: { height: 8, backgroundColor: '#4a90e2' },
  bigScore: { fontSize: 36, fontWeight: '700' },
  jointRow: { flexDirection: 'row', alignItems: 'center', marginVertical: 2 },
  jointName: { width: 72, fontSize: 11, color: '#333' },
  jointBarBg: { flex: 1, height: 8, backgroundColor: '#e0e0e0', borderRadius: 4, overflow: 'hidden', marginHorizontal: 4 },
  jointBarFg: { height: 8 },
  jointVal: { width: 40, fontSize: 11, textAlign: 'right' },
  feedbackBox: {
    backgroundColor: '#fff', borderRadius: 6, padding: 8,
    borderWidth: 1, borderColor: '#e0e0e0', minHeight: 60,
  },
  feedbackLine: { fontSize: 12, color: '#222', marginVertical: 2 },
});
