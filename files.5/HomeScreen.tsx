import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator, Alert, FlatList, Pressable, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { fetchPresets, pingServer, PresetInfo } from '../api/rest';

type Props = {
  initialServerUrl: string;
  onStart: (serverUrl: string, preset: PresetInfo, record: boolean) => void;
};

export const HomeScreen: React.FC<Props> = ({ initialServerUrl, onStart }) => {
  const [serverUrl, setServerUrl] = useState(initialServerUrl);
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [record, setRecord] = useState(true);
  const [loading, setLoading] = useState(false);
  const [serverOk, setServerOk] = useState<boolean | null>(null);

  const refresh = async () => {
    setLoading(true);
    setServerOk(null);
    try {
      const ok = await pingServer(serverUrl);
      setServerOk(ok);
      if (ok) {
        const list = await fetchPresets(serverUrl);
        setPresets(list);
        if (list.length > 0 && !selected) setSelected(list[0].name);
      } else {
        setPresets([]);
      }
    } catch (e) {
      Alert.alert('Lỗi', `Không kết nối được server: ${String(e)}`);
      setServerOk(false);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPressStart = () => {
    if (!selected) {
      Alert.alert('Chưa chọn preset', 'Vui lòng chọn một preset.');
      return;
    }
    const p = presets.find((x) => x.name === selected);
    if (!p) return;
    onStart(serverUrl, p, record);
  };

  return (
    <View style={styles.root}>
      <Text style={styles.title}>Motion Compare</Text>

      <Text style={styles.label}>Server URL</Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={serverUrl}
          onChangeText={setServerUrl}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="http://192.168.1.10:8000"
        />
        <Pressable style={styles.btnSmall} onPress={refresh}>
          <Text style={styles.btnSmallText}>Test</Text>
        </Pressable>
      </View>
      <Text style={styles.dim}>
        {serverOk === null ? '...' : serverOk ? '✓ Server OK' : '✗ Không kết nối'}
      </Text>

      <Text style={[styles.label, { marginTop: 12 }]}>Preset</Text>
      {loading ? (
        <ActivityIndicator />
      ) : presets.length === 0 ? (
        <Text style={styles.dim}>
          Chưa có preset nào. Trên máy server chạy:
          {'\n'}python motion-compare/build_reference.py --video input-videos/{'<file>'}.mp4
        </Text>
      ) : (
        <FlatList
          data={presets}
          keyExtractor={(it: PresetInfo) => it.name}
          renderItem={({ item }: { item: PresetInfo }) => {
            const isSel = item.name === selected;
            return (
              <Pressable
                onPress={() => setSelected(item.name)}
                style={[styles.presetRow, isSel && styles.presetRowSel]}
              >
                <Text style={[styles.presetName, isSel && styles.presetNameSel]}>
                  {item.name}
                </Text>
                <Text style={styles.dim}>
                  {item.num_frames} frames · {item.fps.toFixed(1)} fps · {item.duration_sec}s
                </Text>
              </Pressable>
            );
          }}
        />
      )}

      <Pressable style={styles.recordRow} onPress={() => setRecord(!record)}>
        <View style={[styles.checkbox, record && styles.checkboxOn]}>
          {record && <Text style={styles.checkboxTick}>✓</Text>}
        </View>
        <Text style={styles.recordText}>Lưu video + JSON sau phiên</Text>
      </Pressable>

      <Pressable
        style={[styles.btnPrimary, (!selected || !serverOk) && styles.btnDisabled]}
        onPress={onPressStart}
        disabled={!selected || !serverOk}
      >
        <Text style={styles.btnPrimaryText}>▶ Bắt đầu</Text>
      </Pressable>
    </View>
  );
};

const styles = StyleSheet.create({
  root: { flex: 1, padding: 16, backgroundColor: '#fff' },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 12 },
  label: { fontSize: 12, fontWeight: '600', color: '#444', marginBottom: 4 },
  dim: { fontSize: 11, color: '#666', marginTop: 2 },
  row: { flexDirection: 'row', alignItems: 'center' },
  input: {
    flex: 1, height: 40, borderWidth: 1, borderColor: '#ccc', borderRadius: 6,
    paddingHorizontal: 10, fontSize: 13,
  },
  btnSmall: {
    height: 40, marginLeft: 8, paddingHorizontal: 14, justifyContent: 'center',
    backgroundColor: '#4a90e2', borderRadius: 6,
  },
  btnSmallText: { color: '#fff', fontWeight: '600' },
  presetRow: {
    padding: 12, borderWidth: 1, borderColor: '#e0e0e0', borderRadius: 6,
    marginVertical: 3,
  },
  presetRowSel: { borderColor: '#4a90e2', backgroundColor: '#e8f1fc' },
  presetName: { fontSize: 14, fontWeight: '500' },
  presetNameSel: { color: '#4a90e2' },
  recordRow: { flexDirection: 'row', alignItems: 'center', marginVertical: 12 },
  checkbox: {
    width: 20, height: 20, borderWidth: 1, borderColor: '#888',
    borderRadius: 3, justifyContent: 'center', alignItems: 'center', marginRight: 8,
  },
  checkboxOn: { backgroundColor: '#4a90e2', borderColor: '#4a90e2' },
  checkboxTick: { color: '#fff', fontSize: 14, fontWeight: '700' },
  recordText: { fontSize: 13 },
  btnPrimary: {
    height: 48, backgroundColor: '#4a90e2', borderRadius: 6,
    justifyContent: 'center', alignItems: 'center', marginTop: 8,
  },
  btnDisabled: { backgroundColor: '#bbb' },
  btnPrimaryText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
