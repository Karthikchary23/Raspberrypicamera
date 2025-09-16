import asyncio
import json
import cv2
import websockets

from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaBlackhole
from av import VideoFrame

# Custom video track using OpenCV camera
class CameraStreamTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)  # 0 = default camera

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ret, frame = self.cap.read()
        if not ret:
            raise Exception("Camera not available")

        # Convert frame to VideoFrame
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


async def run():
    uri = "ws://192.168.0.110:8000"  # signaling server
    pc = RTCPeerConnection()

    # Add camera track
    pc.addTrack(CameraStreamTrack())

    async with websockets.connect(uri) as ws:
        # Register Pi
        await ws.send(json.dumps({"type": "registerraspberrypi", "uniqueId": "raspberrypi@123"}))

        # Handle signaling
        async for message in ws:
            msg = json.loads(message)

            if msg["type"] == "offer":
                print("?? Received OFFER from controller")
                await pc.setRemoteDescription(RTCSessionDescription(msg["sdp"], msg["type"]))

                # Create answer
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                # Send answer back
                await ws.send(json.dumps({
                    "type": "answer",
                    "uniqueId": "raspberrypi@123",
                    "sdp": pc.localDescription.sdp
                }))

            elif msg["type"] == "ice-candidate":
                try:
                    await pc.addIceCandidate(msg["candidate"])
                except Exception as e:
                    print("? Error adding ICE candidate:", e)

        @pc.on("icecandidate")
        async def on_icecandidate(event):
            if event.candidate:
                await ws.send(json.dumps({
                    "type": "ice-candidate",
                    "uniqueId": "raspberrypi@123",
                    "candidate": event.candidate.toJSON()
                }))


asyncio.run(run())
