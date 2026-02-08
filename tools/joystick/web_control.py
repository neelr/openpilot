#!/usr/bin/env python3
"""
Arrow key steering control webserver with live video for Comma 3X.
"""
import json
import threading
import time
import io
from http.server import HTTPServer, BaseHTTPRequestHandler

import cv2
import numpy as np
from PIL import Image

from cereal import messaging
from msgq.visionipc import VisionIpcClient, VisionStreamType

PORT = 3000
SEND_RATE = 100
VIDEO_FPS = 15

HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>Comma Steering</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: system-ui, sans-serif;
            background: #1a1a2e; color: #eee;
            min-height: 100vh;
            display: flex; flex-direction: column;
            align-items: center; padding: 20px;
            user-select: none;
        }
        h1 { margin-bottom: 15px; color: #00d4ff; font-size: 24px; }
        .video-container {
            width: 100%; max-width: 640px;
            margin-bottom: 20px;
            border-radius: 12px; overflow: hidden;
            background: #000;
        }
        .video-container img {
            width: 100%; display: block;
        }
        .bar-container {
            width: 100%; max-width: 400px; height: 50px;
            background: #2a2a4a; border-radius: 25px;
            position: relative; margin-bottom: 20px;
        }
        .bar {
            position: absolute; top: 8px; bottom: 8px;
            background: linear-gradient(90deg, #00d4ff, #00ff88);
            border-radius: 17px; transition: all 0.05s;
        }
        .center { position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; background: #666; }
        .value { font-size: 36px; font-weight: bold; font-family: monospace; margin-bottom: 20px; }
        .keys { display: flex; gap: 15px; }
        .key {
            width: 70px; height: 70px;
            background: #2a2a4a; border: 2px solid #444;
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 28px; transition: all 0.1s;
        }
        .key.active { background: #00d4ff; border-color: #00d4ff; color: #1a1a2e; }
        .info { margin-top: 20px; color: #666; font-size: 12px; }
    </style>
</head>
<body>
    <h1>Comma Steering Control</h1>
    <div class="video-container">
        <img src="/video" alt="Road Camera">
    </div>
    <div class="bar-container">
        <div class="center"></div>
        <div class="bar" id="bar"></div>
    </div>
    <div class="value" id="val">0.00</div>
    <div class="keys">
        <div class="key" id="L">&#8592;</div>
        <div class="key" id="R">&#8594;</div>
    </div>
    <div class="info">Arrow keys or tap buttons</div>
<script>
let steer = 0, target = 0;
const RAMP = 2.0;

function update() {
    const dt = 1/60, diff = target - steer, max = RAMP * dt;
    steer = Math.abs(diff) < max ? target : steer + (diff > 0 ? max : -max);
    
    fetch("/steer", {method: "POST", body: JSON.stringify({s: steer})});
    
    const bar = document.getElementById("bar");
    bar.style.width = Math.abs(steer) * 50 + "%";
    bar.style.left = (steer < 0 ? 50 - Math.abs(steer) * 50 : 50) + "%";
    document.getElementById("val").textContent = (steer >= 0 ? "+" : "") + steer.toFixed(2);
    requestAnimationFrame(update);
}

document.onkeydown = e => {
    if (e.key === "ArrowLeft") { target = -1; document.getElementById("L").classList.add("active"); }
    if (e.key === "ArrowRight") { target = 1; document.getElementById("R").classList.add("active"); }
};
document.onkeyup = e => {
    if (e.key === "ArrowLeft") { target = 0; document.getElementById("L").classList.remove("active"); }
    if (e.key === "ArrowRight") { target = 0; document.getElementById("R").classList.remove("active"); }
};

["L", "R"].forEach((id, i) => {
    const el = document.getElementById(id);
    el.ontouchstart = e => { target = i ? 1 : -1; el.classList.add("active"); e.preventDefault(); };
    el.ontouchend = () => { target = 0; el.classList.remove("active"); };
});

update();
</script>
</body>
</html>'''


# Steering controller
class Controller:
    def __init__(self):
        self.pm = messaging.PubMaster(['testJoystick'])
        self.steer = 0.0
        self.lock = threading.Lock()

    def set_steer(self, v):
        with self.lock:
            self.steer = max(-1.0, min(1.0, v))

    def loop(self):
        while True:
            with self.lock:
                s = self.steer
            msg = messaging.new_message('testJoystick')
            msg.testJoystick.axes = [0.0, s]
            msg.testJoystick.buttons = []
            self.pm.send('testJoystick', msg)
            time.sleep(1.0 / SEND_RATE)


# Video streamer
class VideoStreamer:
    def __init__(self):
        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = True

    def camera_loop(self):
        """Subscribe to camera and encode frames as JPEG."""
        vipc = VisionIpcClient("camerad", VisionStreamType.ROAD, False)
        
        while self.running:
            if not vipc.connect(False):
                time.sleep(0.1)
                continue
                
            while vipc.is_connected() and self.running:
                buf = vipc.recv()
                if buf is None:
                    continue
                    
                try:
                    # Get frame dimensions from buffer
                    w, h = buf.width, buf.height
                    
                    # Convert YUV420 to RGB
                    yuv = np.frombuffer(buf.data, dtype=np.uint8).reshape((h * 3 // 2, w))
                    rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_NV12)
                    
                    # Resize for bandwidth (optional)
                    rgb = cv2.resize(rgb, (640, 360))
                    
                    # Encode as JPEG
                    img = Image.fromarray(rgb)
                    buf_io = io.BytesIO()
                    img.save(buf_io, format='JPEG', quality=70)
                    
                    with self.lock:
                        self.latest_frame = buf_io.getvalue()
                        
                except Exception as e:
                    print(f"Frame error: {e}")
                    
                time.sleep(1.0 / VIDEO_FPS)

    def get_frame(self):
        with self.lock:
            return self.latest_frame


ctrl = Controller()
video = VideoStreamer()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
            
        elif self.path == '/video':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            
            try:
                while True:
                    frame = video.get_frame()
                    if frame:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    time.sleep(1.0 / VIDEO_FPS)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/steer':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            ctrl.set_steer(data.get('s', 0))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def main():
    print('=' * 40)
    print('Comma Steering Control + Video')
    print('=' * 40)
    print()
    print('SSH tunnel:')
    print('  ssh -L 3000:localhost:3000 comma@<IP>')
    print()
    print('Then open: http://localhost:3000')
    print()

    # Start steering loop
    threading.Thread(target=ctrl.loop, daemon=True).start()
    
    # Start video capture
    threading.Thread(target=video.camera_loop, daemon=True).start()
    
    # Start HTTP server
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
