import asyncio
import json
import re
from aiohttp import ClientSession, WSMsgType
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCIceCandidate, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaStreamTrack
from picamera2 import Picamera2
import av
from fractions import Fraction

SIGNALING_SERVER = "ws://192.168.31.152:8000"
UNIQUE_ID = "raspberrypi@123"
CONTROLLER_ID = "controller@123"

class PiCameraTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (640, 480)}
        )
        self.picam2.configure(config)
        self.picam2.set_controls({"AwbEnable": False})  # Disable auto white balance
        self.picam2.start()
        self.frame_count = 0

    async def recv(self):
        try:
            frame = self.picam2.capture_array()
            print("✅ PI: Captured video frame")
            # Convert to YUV420P for better WebRTC compatibility
            video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
            video_frame = video_frame.reformat(format="yuv420p")  # Convert to YUV420P
            video_frame.pts = self.frame_count * 1000
            video_frame.time_base = Fraction(1, 90000)
            self.frame_count += 1
            return video_frame
        except Exception as e:
            print(f"❌ PI: Error capturing frame: {e}")
            return None

def extract_ice_candidates(sdp):
    candidates = []
    sdp_lines = sdp.splitlines()
    sdp_mid = None
    sdp_mline_index = -1
    for line in sdp_lines:
        if line.startswith("m="):
            sdp_mline_index += 1
            sdp_mid = line.split()[2]
        if line.startswith("a=candidate:"):
            candidate = line[2:]
            candidates.append({
                "candidate": candidate,
                "sdpMid": sdp_mid,
                "sdpMLineIndex": sdp_mline_index
            })
    print(f"✅ PI: Extracted {len(candidates)} ICE candidates: {candidates}")
    return candidates

async def run():
    ice_servers = [
        RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
        RTCIceServer(
            urls=["turn:openrelay.metered.ca:80"],
            username="openrelayproject",
            credential="openrelayproject"
        )
    ]
    rtc_config = RTCConfiguration(iceServers=ice_servers)
    pc = RTCPeerConnection(rtc_config)

    video_track = PiCameraTrack()
    pc.addTrack(video_track)

    gathering_complete = asyncio.Event()

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print(f"--- PI: ICE gathering state: {pc.iceGatheringState}")
        if pc.iceGatheringState == "complete":
            gathering_complete.set()

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"--- PI: ICE connection state: {pc.iceConnectionState}")

    @pc.on("signalingstatechange")
    async def on_signalingstatechange():
        print(f"--- PI: Signaling state: {pc.signalingState}")

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

                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)
                        print("✅ PI: Local description set (Answer created)")
                        print(f"Answer SDP:\n{pc.localDescription.sdp}")

                        await gathering_complete.wait()
                        print("✅ PI: ICE gathering complete")

                        candidates = extract_ice_candidates(pc.localDescription.sdp)
                        for candidate in candidates:
                            await ws.send_json({
                                "type": "ice-candidate",
                                "uniqueId": UNIQUE_ID,
                                "to": CONTROLLER_ID,
                                "candidate": candidate
                            })
                            print(f"✅ PI: Sent ICE candidate to controller: {candidate['candidate']}")

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
                            print("✅ PI: Added ICE candidate from controller")
                        except Exception as e:
                            print(f"❌ PI: Error adding ICE candidate: {e}")

                elif msg.type == WSMsgType.CLOSED:
                    print("WebSocket connection closed")
                    break
                elif msg.type == WSMsgType.ERROR:
                    print("WebSocket error")
                    break

            print("Exiting run()")

if __name__ == "__main__":
    asyncio.run(run())
