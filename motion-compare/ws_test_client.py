import asyncio
import websockets
import json
import base64
import time
import cv2
import numpy as np

URI = "ws://localhost:8000/ws/compare"

async def main():
    async with websockets.connect(URI, max_size=None) as ws:
        print('connected')
        await ws.send(json.dumps({"type":"init","preset":"Forehand-Demo"}))
        msg = await ws.recv()
        print('init reply:', msg)
        for i in range(30):
            frame = np.full((480,640,3), 255, dtype=np.uint8)
            # draw a moving dot so pose model may see something
            cv2.circle(frame, (int(320+100*np.sin(i/5.0)), 240), 10, (0,0,255), -1)
            ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            b64 = base64.b64encode(buf.tobytes()).decode('ascii')
            await ws.send(json.dumps({"type":"frame","image":b64,"client_ts":int(time.time()*1000)}))
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print('frame resp:', resp[:200])
            except asyncio.TimeoutError:
                print('no reply for frame', i)
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type":"stop"}))
        try:
            final = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print('final:', final)
        except asyncio.TimeoutError:
            pass

if __name__ == '__main__':
    asyncio.run(main())
