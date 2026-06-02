// REST endpoints helper.

export type PresetInfo = {
  name: string;
  num_frames: number;
  fps: number;
  width: number;
  height: number;
  duration_sec: number;
};

export async function fetchPresets(serverUrl: string): Promise<PresetInfo[]> {
  const res = await fetch(`${serverUrl}/presets`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = (await res.json()) as { presets: PresetInfo[] };
  return (data.presets || []).filter((p) => p.num_frames > 0);
}

export async function pingServer(serverUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${serverUrl}/`, { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
