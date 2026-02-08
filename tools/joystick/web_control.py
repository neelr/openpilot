#!/usr/bin/env python3
"""
Arrow key steering control webserver for Comma 3X.
Uses only standard library - no websockets needed.
"""
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from cereal import messaging

PORT = 3000
SEND_RATE = 100

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
            height: 100vh;
            display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            user-select: none;
        }
        h1 { margin-bottom: 20px; color: #00d4ff; }
        .bar-container {
            width: 400px; height: 60px;
            background: #2a2a4a; border-radius: 30px;
            position: relative; margin-bottom: 30px;
        }
        .bar {
            position: absolute; top: 10px; bottom: 10px;
            background: linear-gradient(90deg, #00d4ff, #00ff88);
            border-radius: 20px; transition: all 0.05s;
        }
        .center { position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; background: #666; }
        .value { font-size: 48px; font-weight: bold; font-family: monospace; margin-bottom: 40px; }
        .keys { display: flex; gap: 20px; }
        .key {
            width: 80px; height: 80px;
            background: #2a2a4a; border: 2px solid #444;
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 32px; transition: all 0.1s;
        }
        .key.active { background: #00d4ff; border-color: #00d4ff; color: #1a1a2e; }
        .info { margin-top: 40px; color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <h1>Comma Steering</h1>
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


ctrl = Controller()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(HTML.encode())

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
    print('Comma Steering Control')
    print('=' * 40)
    print()
    print('SSH tunnel:')
    print('  ssh -L 3000:localhost:3000 comma@<IP>')
    print()
    print('Then open: http://localhost:3000')
    print()

    threading.Thread(target=ctrl.loop, daemon=True).start()
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
