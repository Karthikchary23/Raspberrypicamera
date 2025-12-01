import cv2
import socket
import struct
import pickle
from picamera2 import Picamera2

# Create socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind(('0.0.0.0', 8485))
server_socket.listen(1)
print("?? Waiting for connection...")
conn, addr = server_socket.accept()
print(f"? Connected by {addr}")

# Configure Picamera2
picam2 = Picamera2()
config = picam2.create_video_configuration(
    main={"size": (1920, 1080), "format": "RGB888"},
    controls={"FrameDurationLimits": (int(1e6/15), int(1e6/15))}  # ~15 FPS
)
picam2.configure(config)
picam2.start()

encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]  # balance quality/speed

try:
    while True:
        frame = picam2.capture_array()
        result, frame = cv2.imencode('.jpg', frame, encode_param)
        data = pickle.dumps(frame, protocol=pickle.HIGHEST_PROTOCOL)
        conn.sendall(struct.pack(">L", len(data)) + data)
except (BrokenPipeError, ConnectionResetError):
    print("? Client disconnected.")
finally:
    picam2.stop()
    conn.close()
    server_socket.close()

