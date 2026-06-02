import Constants from 'expo-constants';
import { StatusBar } from 'expo-status-bar';
import React, { useState } from 'react';
import { Alert, SafeAreaView, StyleSheet } from 'react-native';
import { PresetInfo } from './src/api/rest';
import { CompareScreen } from './src/screens/CompareScreen';
import { HomeScreen } from './src/screens/HomeScreen';

type Route =
  | { name: 'home' }
  | { name: 'compare'; serverUrl: string; preset: PresetInfo; record: boolean };

const DEFAULT_SERVER_URL =
  (Constants.expoConfig?.extra?.serverUrl as string) ?? 'http://192.168.1.10:8000';

export default function App() {
  const [route, setRoute] = useState<Route>({ name: 'home' });

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="auto" />
      {route.name === 'home' && (
        <HomeScreen
          initialServerUrl={DEFAULT_SERVER_URL}
          onStart={(serverUrl, preset, record) =>
            setRoute({ name: 'compare', serverUrl, preset, record })
          }
        />
      )}
      {route.name === 'compare' && (
        <CompareScreen
          serverUrl={route.serverUrl}
          preset={route.preset}
          record={route.record}
          onExit={(session) => {
            if (session) {
              Alert.alert(
                'Đã lưu phiên',
                `Video: ${session.videoUrl}\nReport: ${session.reportUrl}`,
              );
            }
            setRoute({ name: 'home' });
          }}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' },
});
