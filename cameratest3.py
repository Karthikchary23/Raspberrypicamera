import asyncio
import json
from aiohttp import ClientSession, WSMsgType
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
    RTCIceCandidate,
    RTCConfiguration,
    RTCIceServer,
)
from picamera2 import Picamera2
import av
import cv2
from fractions import Fraction
import time
import os
import sys

SIGNALING_SERVER = "wss://raspberrypicamerabackend.onrender.com"
UNIQUE_ID = "raspberrypi@123"
CONTROLLER_ID = "controller@123"

class PiCameraTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (320, 240)}  # Reduced resolution
        )
        self.picam2.configure(config)
        self.picam2.set_controls({"AwbEnable": False, "Framerate": 15})  # Lower framerate
        self.picam2.start()
        self.frame_count = 0

    async def recv(self):
        try:
            frame = self.picam2.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
            video_frame = video_frame.reformat(format="yuv420p")
            video_frame.pts = self.frame_count * 1000
            video_frame.time_base = Fraction(1, 90000)
            self.frame_count += 1
            return video_frame
        except Exception as e:
            print(f"❌ PI: Error capturing frame: {e}")
            return None

async def run():
    ice_servers = [
        RTCIceServer(urls="stun:stun.l.google.com:19302"),
        RTCIceServer(urls="stun:stun1.l.google.com:19302"),
        RTCIceServer(
            urls="turn:openrelay.metered.ca:80",
            username="openrelayproject",
            credential="openrelayproject"
        ),
        RTCIceServer(
            urls="turn:35.244.34.75:3478",
            username="revon",
            credential="revon@2025!@#$%^&*()@2025"
        ),
    ]
    rtc_config = RTCConfiguration(iceServers=ice_servers)
    pc = RTCPeerConnection(rtc_config)

    video_track = PiCameraTrack()
    pc.addTrack(video_track)

    gathering_complete = asyncio.Event()

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        if candidate:
            await ws.send_json({
                "type": "ice-candidate",
                "uniqueId": UNIQUE_ID,
                "to": CONTROLLER_ID,
                "candidate": {
                    "candidate": str(candidate.candidate),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex
                }
            })
            print(f"✅ PI: Sent ICE candidate: type={candidate.type}, address={candidate.address}")

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print(f"--- PI: ICE gathering state: {pc.iceGatheringState}")
        if pc.iceGatheringState == "complete":
            gathering_complete.set()

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"--- PI: ICE connection state: {pc.iceConnectionState}")
        if pc.iceConnectionState in ["failed", "disconnected"]:
            print("❌ PI: ICE failed/disconnected - check NAT/TURN")

    @pc.on("signalingstatechange")
    async def on_signalingstatechange():
        print(f"--- PI: Signaling state: {pc.signalingState}")

    @pc.on("track")
    def on_track(track):
        print(f"✅ PI: Received remote track: kind={track.kind}")

    channel = pc.createDataChannel("test")

    @channel.on("open")
    async def on_open():
        print("✅ PI: Data channel open, sending test message")
        await channel.send("Hello from Pi")

    @channel.on("message")
    async def on_message(message):
        print(f"✅ PI: Received data channel message: {message}")

    async with ClientSession() as session:
        async with session.ws_connect(SIGNALING_SERVER) as ws:
            await ws.send_json({"type": "registerraspberrypi", "uniqueId": UNIQUE_ID})
            print("✅ Registered Pi with signaling server")

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "offer":
                        print("© PI: Received OFFER")
                        print(f"Offer SDP:\n{data['sdp']}")
                        offer = RTCSessionDescription(sdp=data["sdp"], type="offer")
                        await pc.setRemoteDescription(offer)
                        print("✅ PI: Remote description set")
                        print(f"Signaling state: {pc.signalingState}")
                        print(f"ICE connection state: {pc.iceConnectionState}")

                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)
                        print("✅ PI: Local description set (Answer created)")
                        print(f"Answer SDP:\n{pc.localDescription.sdp}")

                        await gathering_complete.wait()
                        print("✅ PI: ICE gathering complete")

                        await ws.send_json({
                            "type": "answer",
                            "uniqueId": UNIQUE_ID,
                            "sdp": pc.localDescription.sdp,
                            "to": CONTROLLER_ID
                        })
                        print("✅ PI: Sent ANSWER to controller")

                    elif msg_type == "ice-candidate" and "candidate" in data:
                        print("© PI: Received ICE candidate from controller")
                        candidate_data = data["candidate"]
                        try:
                            ice = RTCIceCandidate(
                                sdpMid=candidate_data.get("sdpMid"),
                                sdpMLineIndex=candidate_data.get("sdpMLineIndex"),
                                candidate=candidate_data.get("candidate")
                            )
                            await pc.addIceCandidate(ice)
                            print(f"✅ PI: Added ICE candidate: type={ice.type}, address={ice.address}")
                        except Exception as e:
                            print(f"❌ PI: Error adding ICE candidate: {e}")
                    elif msg_type == "disconnect":
                        print("❓ Received disconnect, restarting...")
                        await pc.close()
                        time.sleep(2)
                        os.execv(sys.executable, ['python3'] + sys.argv)

                elif msg.type == WSMsgType.CLOSED:
                    print("WebSocket connection closed")
                    break
                elif msg.type == WSMsgType.ERROR:
                    print("WebSocket error")
                    break

            print("Exiting run()")

if __name__ == "__main__":
    asyncio.run(run())
