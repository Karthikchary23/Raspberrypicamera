import asyncio
import json
from aiohttp import web, ClientSession, WSMsgType
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCIceCandidate
from picamera2 import Picamera2
import cv2
import numpy as np
import av

SIGNALING_SERVER = "ws://192.168.31.152:8000"  # Replace with your signaling server
UNIQUE_ID = "raspberrypi@123"
CONTROLLER_ID = "controller@123"

# --- Custom VideoTrack using Picamera2 ---
class PiCameraTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(main={"format": "RGB888", "size": (640, 480)})
        self.picam2.configure(config)
        self.picam2.start()

    async def recv(self):
        frame = self.picam2.capture_array()
        # Convert to av.VideoFrame
        video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = None
        video_frame.time_base = None
        return video_frame

def parse_ice_candidate(candidate_str):
    """Parse an ICE candidate string into its components."""
    # Remove the "candidate:" prefix if present
    if candidate_str.startswith("candidate:"):
        candidate_str = candidate_str[10:]
    
    # Split the candidate string into parts
    parts = candidate_str.split()
    if len(parts) < 8:
        raise ValueError(f"Invalid ICE candidate format: {candidate_str}")
    
    # Extract required fields
    foundation = parts[0]
    component = int(parts[1])
    protocol = parts[2]
    priority = int(parts[3])
    ip = parts[4]
    port = int(parts[5])
    candidate_type = parts[7]  # After 'typ'
    
    # Initialize result
    result = {
        "foundation": foundation,
        "component": component,
        "protocol": protocol,
        "priority": priority,
        "ip": ip,
        "port": port,
        "type": candidate_type,
        "relatedAddress": None,
        "relatedPort": None
    }
    
    # Parse optional fields (raddr, rport)
    for i in range(8, len(parts)):
        if parts[i] == "raddr":
            result["relatedAddress"] = parts[i + 1]
        elif parts[i] == "rport":
            result["relatedPort"] = int(parts[i + 1])
    
    return result

# --- Main asyncio run ---
async def run():
    pc = RTCPeerConnection()
    video_track = PiCameraTrack()
    pc.addTrack(video_track)

    async with ClientSession() as session:
        async with session.ws_connect(SIGNALING_SERVER) as ws:
            # Register Raspberry Pi
            await ws.send_json({"type": "registerraspberrypi", "uniqueId": UNIQUE_ID})
            print("? Registered Pi with signaling server")

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "start_video":
                        print("?? Start video signal received")

                    elif msg_type == "offer":
                        print("?? Received OFFER")
                        offer = RTCSessionDescription(sdp=data["sdp"], type="offer")
                        await pc.setRemoteDescription(offer)

                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)

                        await ws.send_json({
                            "type": "answer",
                            "uniqueId": UNIQUE_ID,
                            "sdp": pc.localDescription.sdp,
                            "to": CONTROLLER_ID
                        })
                        print("? Sent ANSWER to controller")

                    elif msg_type == "ice-candidate" and "candidate" in data:
                        print("Data from candidates ICE:", data)
                        candidate_data = data["candidate"]
                        try:
                            # Validate required fields
                            if not all(key in candidate_data for key in ["candidate", "sdpMid", "sdpMLineIndex"]):
                                print(f"Invalid ICE candidate data: {candidate_data}")
                                continue
                            
                            # Parse the candidate string
                            parsed_candidate = parse_ice_candidate(candidate_data.get("candidate"))
                            
                            # Create RTCIceCandidate with parsed components
                            ice = RTCIceCandidate(
                                foundation=parsed_candidate["foundation"],
                                ip=parsed_candidate["ip"],
                                port=parsed_candidate["port"],
                                priority=parsed_candidate["priority"],
                                protocol=parsed_candidate["protocol"],
                                type=parsed_candidate["type"],
                                component=parsed_candidate["component"],
                                sdpMid=candidate_data.get("sdpMid"),
                                sdpMLineIndex=candidate_data.get("sdpMLineIndex"),
                                relatedAddress=parsed_candidate.get("relatedAddress"),
                                relatedPort=parsed_candidate.get("relatedPort")
                            )
                            await pc.addIceCandidate(ice)
                            print("? Added ICE candidate from controller")
                        except Exception as e:
                            print(f"Error adding ICE candidate: {e}")

asyncio.run(run())
