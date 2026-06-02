import { CameraView, useCameraPermissions } from 'expo-camera';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Pressable, StyleSheet, Text, View,
} from 'react-native';
import { CompareSocket } from '../api/ws';
import { PresetInfo } from '../api/rest';
import { SkeletonOverlay } from '../components/SkeletonOverlay';
import { ScorePanel } from '../components/ScorePanel';

type Props = {
  serverUrl: string;
  preset: PresetInfo;
  record: boolean;
  onExit: (session?: { videoUrl: string; reportUrl: string }) => void;
};

// Tốc độ gửi frame. Server CPU thường handle 10-15 FPS, dùng 8 cho an toàn.
const TARGET_FPS = 8;
const FRAME_INTERVAL_MS = Math.round(1000 / TARGET_FPS);

export const CompareScreen: React.FC<Props> = ({ serverUrl, preset, record, onExit }) => {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView | null>(null);
  const wsRef = useRef<CompareSocket | null>(null);
  const captureLoopRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inFlightRef = useRef(false);

  // Layout của camera view (để overlay SVG đúng kích thước)
  const [viewSize, setViewSize] = useState({ w: 0, h: 0 });

  // State render
  const [status, setStatus] = useState<'connecting' | 'ready' | 'running' | 'done' | 'error'>('connecting');
  const [errorMsg, setErrorMsg] = useState('');
  const [overall, setOverall] = useState(0);
  const [perJoint, setPerJoint] = useState<Array<number | null>>(Array(17).fill(null));
  const [feedback, setFeedback] = useState<string[]>([]);
  const [refIdx, setRefIdx] = useState(0);
  const [valid, setValid] = useState(false);
  const [kpts, setKpts] = useState<Array<[number, number]>>([]);
  const [kptsConf, setKptsConf] = useState<number[]>([]);
  const [frameSize, setFrameSize] = useState({ w: 0, h: 0 });

  // FPS counter (đo qua client_ts echo)
  const fpsWindowRef = useRef<number[]>([]);
  const [fps, setFps] = useState(0);

  // ----- Init permission -----
  useEffect(() => {
    if (!permission) return;
    if (!permission.granted) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  // ----- Connect WS -----
  useEffect(() => {
    const sock = new CompareSocket(serverUrl, {
      onOpen: () => {
        sock.send({ type: 'init', preset: preset.name, record });
      },
      onReady: () => {
        setStatus('ready');
      },
      onResult: (e) => {
        setStatus('running');
        setOverall(e.overall);
        setPerJoint(e.per_joint);
        setFeedback(e.feedback);
        setRefIdx(e.ref_idx);
        setValid(e.valid);
        setKpts(e.kpts);
        setKptsConf(e.kpts_conf);
        setFrameSize({ w: e.frame_w, h: e.frame_h });
        // FPS
        if (e.client_ts) {
          const dt = Date.now() - e.client_ts;
          const win = fpsWindowRef.current;
          win.push(dt);
          if (win.length > 20) win.shift();
          const avg = win.reduce((a, b) => a + b, 0) / win.length;
          if (avg > 0) setFps(1000 / avg);
        }
        inFlightRef.current = false;
      },
      onDone: () => {
        setStatus('done');
      },
      onSession: (e) => {
        // Lưu URL để truyền ra khi exit
        sessionMetaRef.current = {
          videoUrl: `${serverUrl}${e.video_url}`,
          reportUrl: `${serverUrl}${e.report_url}`,
        };
      },
      onError: (msg) => {
        setStatus('error');
        setErrorMsg(msg);
      },
      onClose: () => {
        // không set state ở đây để tránh đè status 'done'
      },
    });
    sock.connect();
    wsRef.current = sock;
    return () => {
      sock.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverUrl, preset.name, record]);

  const sessionMetaRef = useRef<{ videoUrl: string; reportUrl: string } | null>(null);

  // ----- Capture loop -----
  const captureOnce = useCallback(async () => {
    if (!cameraRef.current || inFlightRef.current) return;
    if (!wsRef.current?.isOpen()) return;
    inFlightRef.current = true;
    try {
      const pic = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.4,        // nén thêm để tiết kiệm băng thông
        skipProcessing: true,
        shutterSound: false,
      });
      if (pic?.base64) {
        wsRef.current.send({
          type: 'frame',
          image: pic.base64,
          client_ts: Date.now(),
        });
      } else {
        inFlightRef.current = false;
      }
    } catch {
      inFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (status !== 'ready' && status !== 'running') return;
    captureLoopRef.current = setInterval(captureOnce, FRAME_INTERVAL_MS);
    return () => {
      if (captureLoopRef.current) {
        clearInterval(captureLoopRef.current);
        captureLoopRef.current = null;
      }
    };
  }, [status, captureOnce]);

  // ----- Handlers -----
  const onStop = () => {
    if (captureLoopRef.current) {
      clearInterval(captureLoopRef.current);
      captureLoopRef.current = null;
    }
    wsRef.current?.send({ type: 'stop' });
    // Chờ session message một chút rồi exit
    setTimeout(() => {
      onExit(sessionMetaRef.current ?? undefined);
    }, 600);
  };

  // ----- Render -----
  if (!permission) {
    return <View style={styles.center}><Text>Đang kiểm tra quyền camera...</Text></View>;
  }
  if (!permission.granted) {
    return (
      <View style={styles.center}>
        <Text style={{ marginBottom: 12 }}>App cần quyền camera để hoạt động.</Text>
        <Pressable style={styles.btn} onPress={requestPermission}>
          <Text style={styles.btnText}>Cấp quyền</Text>
        </Pressable>
      </View>
    );
  }

  if (status === 'error') {
    return (
      <View style={styles.center}>
        <Text style={{ marginBottom: 12, color: '#c00' }}>{errorMsg || 'Lỗi không xác định'}</Text>
        <Pressable style={styles.btn} onPress={() => onExit()}>
          <Text style={styles.btnText}>Quay lại</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      {/* Top: camera + skeleton overlay */}
      <View
        style={styles.cameraWrap}
        onLayout={(e: { nativeEvent: { layout: { width: number; height: number } } }) =>
          setViewSize({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })
        }
      >
        <CameraView
          ref={cameraRef}
          style={StyleSheet.absoluteFill}
          facing="front"
        />
        {viewSize.w > 0 && frameSize.w > 0 && (
          <SkeletonOverlay
            kpts={kpts}
            kptsConf={kptsConf}
            perJoint={perJoint}
            frameW={frameSize.w}
            frameH={frameSize.h}
            viewW={viewSize.w}
            viewH={viewSize.h}
          />
        )}
        <View style={styles.hud}>
          <Text style={styles.hudText}>
            {status === 'connecting' && 'Đang kết nối server...'}
            {status === 'ready' && 'Sẵn sàng. Bắt đầu di chuyển!'}
            {status === 'running' && `Acc ${overall.toFixed(1)}% · FPS ${fps.toFixed(1)} · ref ${refIdx}/${preset.num_frames}`}
            {status === 'done' && 'Đã hết reference'}
          </Text>
        </View>
        <Pressable style={styles.stopBtn} onPress={onStop}>
          <Text style={styles.stopBtnText}>■ Stop</Text>
        </Pressable>
      </View>

      {/* Bottom: score panel */}
      <View style={styles.panelWrap}>
        <ScorePanel
          refIdx={refIdx}
          numRef={preset.num_frames}
          overall={overall}
          perJoint={perJoint}
          feedback={feedback}
          valid={valid}
          fps={fps}
        />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff', padding: 16 },
  cameraWrap: { flex: 1.2, position: 'relative', overflow: 'hidden' },
  panelWrap: { flex: 1, backgroundColor: '#fafafa' },
  hud: {
    position: 'absolute', top: 8, left: 8,
    backgroundColor: 'rgba(0,0,0,0.55)', paddingVertical: 4, paddingHorizontal: 8,
    borderRadius: 4,
  },
  hudText: { color: '#fff', fontSize: 12 },
  stopBtn: {
    position: 'absolute', top: 8, right: 8,
    backgroundColor: '#e63c3c', paddingVertical: 6, paddingHorizontal: 14,
    borderRadius: 6,
  },
  stopBtnText: { color: '#fff', fontWeight: '700' },
  btn: { backgroundColor: '#4a90e2', paddingVertical: 10, paddingHorizontal: 20, borderRadius: 6 },
  btnText: { color: '#fff', fontWeight: '600' },
});
