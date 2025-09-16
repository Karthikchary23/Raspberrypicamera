import asyncio
import websockets
import json
import base64
import cv2
from picamera2 import Picamera2

SERVER_URI = "ws://192.168.31.152:8000"  # Your server IP
PI_UNIQUE_ID = "raspberrypi@123"

async def connect_pi():
    async with websockets.connect(SERVER_URI) as ws:
        print("? Connected to server")

        # Register Raspberry Pi automatically
        await ws.send(json.dumps({
            "type": "registerraspberrypi",
            "uniqueId": PI_UNIQUE_ID
        }))
        print("?? Registered with server")

        picam2 = None
        streaming = False

        while True:
            try:
                # Check for server messages
                message = await asyncio.wait_for(ws.recv(), timeout=0.05)
                data = json.loads(message)

                # Start video if server tells to
                if data.get("type") == "start_video":
                    print("?? Start video command received")
                    if not streaming:
                        picam2 = Picamera2()
                        config = picam2.create_preview_configuration(main={"size": (320, 240)})
                        picam2.configure(config)
                        picam2.start()
                        streaming = True
                        print("?? Camera started")
            except asyncio.TimeoutError:
                pass  # No message received, continue

            # Capture and send frames continuously if streaming
            if streaming and picam2:
                frame = picam2.capture_array()
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                _, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                jpg_as_text = base64.b64encode(buffer).decode('utf-8')

                try:
                    await ws.send(json.dumps({
                        "type": "frame",
                        "uniqueId": PI_UNIQUE_ID,
                        "payload": jpg_as_text
                    }))
                except websockets.ConnectionClosed:
                    print("? Connection closed by server")
                    break

            await asyncio.sleep(0.05)  # ~20 FPS

asyncio.run(connect_pi())
