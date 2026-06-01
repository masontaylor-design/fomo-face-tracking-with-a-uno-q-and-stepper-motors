# Face Tracker Motor Controller — Python side (MPU)
# Arduino UNO Q — App Lab App
#
# BROWSER CAMERA VERSION
# ─────────────────────────────────────────────────────────────────
# The phone opens a webpage (served by this app) in its browser.
# The page uses getUserMedia() to grab camera frames and sends them
# over a second WebSocket connection back to Python.
# No app install needed on the phone. Works in Safari, Chrome, etc.
#
# HOW TO USE
# ──────────
# 1. Run this app as normal.
# 2. On your phone, open:  http://<THIS_COMPUTER_IP>:8899/cam
#    (The app prints the URL on startup.)
# 3. Tap "Allow" when the browser asks for camera permission.
# 4. Leave that tab open — you can open other tabs freely.
# ─────────────────────────────────────────────────────────────────

import asyncio
import os
import ssl
import threading
import time

import cv2
import numpy as np
from aiohttp import web

from arduino.app_utils import App, Bridge


# ── Config ────────────────────────────────────────────────────────
CAM_SERVER_PORT = 8899        # phone opens this in browser
CAM_QUALITY     = 50          # JPEG quality sent from phone (0-100); lower = faster

# ── Tuning ────────────────────────────────────────────────────────
CAM_W = 640
CAM_H = 480

PAN_DEAD_ZONE  = 0.08
PAN_GAIN       = 80
PAN_MAX_SPEED  = 35

TILT_DEAD_ZONE = 0.10
TILT_GAIN      = 50
TILT_MAX_SPEED = 20

SMOOTH_ALPHA   = 0.4
LOST_TIMEOUT   = 1.5

# ── Face detection ────────────────────────────────────────────────
# ── Face detector setup ───────────────────────────────────────────
# Prefer YuNet (neural net) if the model file is present next to main.py,
# otherwise fall back to Haar cascade.
_YUNET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "face_detection_yunet_2023mar.onnx")
_yunet      = None
_clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
_cascade    = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# YuNet detects on a downscaled frame for speed; coords are scaled back up.
# 320x240 is plenty for detection — running at full 640x480 is ~4x slower.
_YUNET_DW, _YUNET_DH = 320, 240

if os.path.exists(_YUNET_PATH):
    try:
        _yunet = cv2.FaceDetectorYN.create(
            _YUNET_PATH, "", (_YUNET_DW, _YUNET_DH),
            score_threshold=0.35,
            nms_threshold=0.3,
            top_k=5,
        )
        print(f"[DET] YuNet loaded (detect res {_YUNET_DW}x{_YUNET_DH})")
    except Exception as e:
        print(f"[DET] YuNet failed to load ({e}), falling back to Haar")
        _yunet = None
else:
    print(f"[DET] YuNet model not found at {_YUNET_PATH}")
    print(f"[DET] Using Haar cascade (less reliable). For best results,")
    print(f"[DET] download face_detection_yunet_2023mar.onnx and place it")
    print(f"[DET] in the same folder as main.py")


# Only run CLAHE when the frame is genuinely dark/low-contrast.
# Skips the LAB conversion entirely under normal indoor lighting.
_CLAHE_THRESH = 80   # 0-255 mean brightness; below this triggers CLAHE

def detect_faces(bgr_frame):
    """Return list of (x, y, w, h, score) face boxes. Uses YuNet if available."""
    if _yunet is not None:
        gray_check = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
        if gray_check.mean() < _CLAHE_THRESH:
            l, a, b = cv2.split(cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2LAB))
            l = _clahe.apply(l)
            bgr_frame = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        _, faces = _yunet.detect(bgr_frame)
        if faces is None:
            return []
        # faces rows: [x, y, w, h, score, ...]
        return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[4])) for f in faces]
    else:
        # Haar fallback
        gray     = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
        enhanced = _clahe.apply(gray)
        faces    = _cascade.detectMultiScale(
            enhanced, scaleFactor=1.1, minNeighbors=3, minSize=(25, 25)
        )
        if len(faces) == 0:
            return []
        return [(x, y, w, h, 1.0) for (x, y, w, h) in faces
                if 0.6 < w / max(h, 1) < 1.6]

# ── State ─────────────────────────────────────────────────────────
last_detection_time = 0.0
motors_stopped      = True
smooth_cx           = 0.5
smooth_cy           = 0.5
first_detection     = True
_conf_threshold     = 0.2

_latest_frame   = None
_frame_lock     = threading.Lock()

# ── App Lab UI brick ──────────────────────────────────────────────

# ── Motor controllers ─────────────────────────────────────────────
def pan_speed(error):
    if abs(error) < PAN_DEAD_ZONE:
        return 0
    scaled = (abs(error) - PAN_DEAD_ZONE) / (0.5 - PAN_DEAD_ZONE)
    s = min(int(scaled * PAN_GAIN), PAN_MAX_SPEED)
    return s if error > 0 else -s

def tilt_speed(error):
    if abs(error) < TILT_DEAD_ZONE:
        return 0
    scaled = (abs(error) - TILT_DEAD_ZONE) / (0.5 - TILT_DEAD_ZONE)
    s = min(int(scaled * TILT_GAIN), TILT_MAX_SPEED)
    return s if error > 0 else -s

# ── aiohttp web server (plain WebSocket — no Socket.IO) ───────────
cam_app = web.Application()

CAM_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Face Tracker — Camera</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0a0a0a; color: #e0e0e0; font-family: monospace;
           display: flex; flex-direction: column; align-items: center;
           justify-content: center; min-height: 100dvh; padding: 24px;
           gap: 16px; text-align: center; }
    h1 { font-size: .9rem; letter-spacing: .3em; color: #00ff88; opacity: .7; text-transform: uppercase; }
    #status { font-size: .85rem; min-height: 1.4em; }
    #status.ok  { color: #00ff88; }
    #status.err { color: #ff4444; }
    video  { width: 100%; max-width: 320px; border-radius: 6px;
             border: 1px solid #00ff8830; display: none; }
    canvas { display: none; }
    #fps   { font-size: .75rem; opacity: .4; }
    p.note { font-size: .75rem; opacity: .4; max-width: 300px; line-height: 1.6; }
  </style>
</head>
<body>
  <h1>&#128247; Camera Feed</h1>
  <div id="status">Connecting&hellip;</div>
  <video id="v" autoplay playsinline muted></video>
  <canvas id="c"></canvas>
  <div id="fps"></div>
  <p class="note">Screen will stay on automatically. Browse freely in other Safari tabs — camera keeps running here.</p>
  <script>
    const statusEl = document.getElementById('status');
    const video    = document.getElementById('v');
    const canvas   = document.getElementById('c');
    const ctx      = canvas.getContext('2d');
    const fpsEl    = document.getElementById('fps');
    const W = 640, H = 480, QUAL = 0.7, MS = 33;
    let ws = null, sending = false;
    let frameCount = 0, fpsTs = Date.now();

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(proto + '://' + location.host + '/ws');
      ws.binaryType = 'arraybuffer';
      ws.onopen  = () => { statusEl.textContent = 'Connected — starting camera…'; statusEl.className = ''; startCamera(); };
      ws.onclose = () => { statusEl.textContent = 'Disconnected — retrying…'; statusEl.className = 'err'; sending = false; setTimeout(connect, 2000); };
      ws.onerror = () => { statusEl.textContent = 'Connection error'; statusEl.className = 'err'; };
    }

    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: W }, height: { ideal: H } }, audio: false });
        video.srcObject = stream;
        video.style.display = 'block';
        video.onloadedmetadata = () => {
          canvas.width = W; canvas.height = H;
          sending = true;
          statusEl.textContent = 'Streaming ✓'; statusEl.className = 'ok';
          sendFrames();
        };
      } catch (err) { statusEl.textContent = 'Camera error: ' + err.message; statusEl.className = 'err'; }
    }

    function sendFrames() {
      if (!sending || !ws || ws.readyState !== WebSocket.OPEN) return;
      ctx.drawImage(video, 0, 0, W, H);
      canvas.toBlob(blob => {
        if (!blob) { setTimeout(sendFrames, MS); return; }
        blob.arrayBuffer().then(buf => {
          ws.send(buf);
          frameCount++;
          const now = Date.now();
          if (now - fpsTs >= 1000) { fpsEl.textContent = frameCount + ' fps'; frameCount = 0; fpsTs = now; }
          setTimeout(sendFrames, MS);
        });
      }, 'image/jpeg', QUAL);
    }

    connect();

    // ── Wake Lock — keeps the screen on so the camera never stops ──
    // Supported in Safari 16.4+ on iOS. Silently does nothing on older versions.
    let wakeLock = null;
    async function requestWakeLock() {
      if (!('wakeLock' in navigator)) return;
      try {
        wakeLock = await navigator.wakeLock.request('screen');
        // Re-acquire if the page becomes visible again (e.g. switching tabs)
        document.addEventListener('visibilitychange', async () => {
          if (document.visibilityState === 'visible') {
            try { wakeLock = await navigator.wakeLock.request('screen'); } catch {}
          }
        });
      } catch {}
    }
    requestWakeLock();
  </script>
</body>
</html>"""

async def cam_page(request):
    return web.Response(text=CAM_PAGE_HTML, content_type='text/html')

async def cam_websocket(request):
    global _latest_frame
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print("[CAM] Phone connected")
    async for msg in ws:
        if msg.type == web.WSMsgType.BINARY:
            try:
                arr = np.frombuffer(msg.data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    if frame.shape[1] != CAM_W or frame.shape[0] != CAM_H:
                        frame = cv2.resize(frame, (CAM_W, CAM_H))
                    with _frame_lock:
                        _latest_frame = frame
            except Exception as e:
                print(f"[CAM] Decode error: {e}")
        elif msg.type == web.WSMsgType.ERROR:
            break
    print("[CAM] Phone disconnected")
    return ws

cam_app.router.add_get('/cam', cam_page)
cam_app.router.add_get('/ws',  cam_websocket)

# ── Certificate paths (stored next to main.py, persist across runs) ──────────
_DIR     = os.path.dirname(os.path.abspath(__file__))
_CA_KEY  = os.path.join(_DIR, 'ca_key.pem')
_CA_CERT = os.path.join(_DIR, 'ca.pem')       # <-- installed on iPhone once
_SRV_KEY = os.path.join(_DIR, 'srv_key.pem')
_SRV_CRT = os.path.join(_DIR, 'srv_cert.pem')

def _ensure_certs(lan_ip):
    """
    Generate a local CA (once ever) and a server cert signed by it.
    The CA cert is what you install on your iPhone — after that the browser
    trusts the server cert with no warnings, camera permission works fine.
    If the LAN IP changes (e.g. different hotspot) the server cert is
    regenerated automatically; you never need to reinstall the CA.
    """
    import ipaddress
    import datetime as dt
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    now = dt.datetime.now(dt.timezone.utc)

    def _pem(path, obj):
        if hasattr(obj, 'private_bytes'):
            data = obj.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.TraditionalOpenSSL,
                                     serialization.NoEncryption())
        else:
            data = obj.public_bytes(serialization.Encoding.PEM)
        with open(path, 'wb') as f:
            f.write(data)

    # ── CA (generated once, never changes — iPhone installs this) ────────────
    if not os.path.exists(_CA_CERT) or not os.path.exists(_CA_KEY):
        print("[TLS] Generating local CA (one-time)…")
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "FaceTracker Local CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FaceTracker"),
        ])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name).issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now.replace(year=now.year + 10))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        _pem(_CA_KEY, ca_key)
        _pem(_CA_CERT, ca_cert)
        print(f"[TLS] CA cert saved → {_CA_CERT}")

    # ── Server cert — regenerate if IP has changed ────────────────────────────
    regen = True
    if os.path.exists(_SRV_CRT) and os.path.exists(_SRV_KEY):
        try:
            with open(_SRV_CRT, 'rb') as f:
                existing = x509.load_pem_x509_certificate(f.read())
            san  = existing.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            ips  = san.value.get_values_for_type(x509.IPAddress)
            if ipaddress.IPv4Address(lan_ip) in ips:
                regen = False
        except Exception:
            pass

    if regen:
        print(f"[TLS] Generating server cert for {lan_ip}…")
        with open(_CA_KEY, 'rb') as f:
            ca_key_obj = serialization.load_pem_private_key(f.read(), password=None)
        with open(_CA_CERT, 'rb') as f:
            ca_cert_obj = x509.load_pem_x509_certificate(f.read())

        srv_key  = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, lan_ip)])
        srv_cert = (
            x509.CertificateBuilder()
            .subject_name(srv_name).issuer_name(ca_cert_obj.subject)
            .public_key(srv_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now.replace(year=now.year + 2))
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.IPv4Address(lan_ip)),
                x509.DNSName(lan_ip),
            ]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key_obj, hashes.SHA256())
        )
        _pem(_SRV_KEY, srv_key)
        _pem(_SRV_CRT, srv_cert)
        print(f"[TLS] Server cert ready.")

def _run_cam_server():
    import socket as _sock
    # HOST_IP env var lets you override the detected IP — needed when running
    # inside Docker where the container IP differs from the host's LAN IP.
    # Set it in app.yaml or pass it manually if the QR code shows the wrong IP.
    # ── SET YOUR PC's IP HERE if the QR code shows the wrong address ─────────
    # e.g. MANUAL_IP = "172.20.10.6"   ← your PC's IP when on iPhone hotspot
    MANUAL_IP = ""   # leave empty to auto-detect
    # ─────────────────────────────────────────────────────────────────────────
    local_ip = MANUAL_IP.strip() or os.environ.get("HOST_IP", "").strip()
    if not local_ip:
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = '127.0.0.1'
    print(f"[CAM] Using host IP: {local_ip}")

    _ensure_certs(local_ip)

    # Serve the CA cert so the phone can download and install it
    async def serve_ca(request):
        with open(_CA_CERT, 'rb') as f:
            data = f.read()
        return web.Response(body=data,
                            content_type='application/x-x509-ca-cert',
                            headers={'Content-Disposition': 'attachment; filename=FaceTrackerCA.pem'})
    cam_app.router.add_get('/cert', serve_ca)

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(_SRV_CRT, _SRV_KEY)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = web.AppRunner(cam_app)
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(
        web.TCPSite(runner, '0.0.0.0', CAM_SERVER_PORT, ssl_context=ssl_ctx).start()
    )

    cam_url  = f'https://{local_ip}:{CAM_SERVER_PORT}/cam'
    cert_url = f'https://{local_ip}:{CAM_SERVER_PORT}/cert'

    # Print QR codes to terminal
    try:
        import qrcode
        def print_qr(url, label):
            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            print(f'\n  {label}:')
            print(f'  {url}')
            qr.print_ascii(invert=True)
        print(f"\n{'='*62}")
        print_qr(cert_url, '1) Download & install CA cert on iPhone (FIRST TIME ONLY)')
        print_qr(cam_url,  '2) Open camera page')
        print(f"\n  FIRST TIME SETUP:")
        print(f"  a) Scan QR 1 in Safari → tap Allow → tap 'Allow' on download prompt")
        print(f"  b) Settings → General → VPN & Device Management")
        print(f"       → FaceTracker Local CA → Install → Install")
        print(f"  c) Settings → General → About → Certificate Trust Settings")
        print(f"       → toggle ON 'FaceTracker Local CA'")
        print(f"  d) Scan QR 2 → allow camera → done!")
        print(f"  After setup, only QR 2 is needed each time.")
        print(f"{'='*62}\n")
    except Exception:
        print(f"\n{'='*62}")
        print(f"  FIRST TIME ONLY — install CA cert on iPhone:")
        print(f"  1) Open in Safari: {cert_url}")
        print(f"     Tap Allow → Settings → General → VPN & Device Management")
        print(f"     → FaceTracker Local CA → Install → Install")
        print(f"     Then: Settings → General → About → Certificate Trust Settings")
        print(f"     → toggle ON 'FaceTracker Local CA'")
        print(f"  2) Camera page: {cam_url}")
        print(f"  After setup, only step 2 is needed each time.")
        print(f"{'='*62}\n")

    loop.run_forever()

threading.Thread(target=_run_cam_server, daemon=True).start()

# ── Detection (runs in its own thread to avoid blocking the loop) ──
_detect_frame   = None
_detect_lock    = threading.Lock()
_detect_event   = threading.Event()

# Detection rate cap — run YuNet at most this many times per second.
# 15fps is plenty for smooth motor control and keeps CPU usage low.
# The motor loop in the Arduino runs independently so nothing stalls.
DETECT_FPS  = 15
DETECT_INTERVAL = 1.0 / DETECT_FPS

def _detection_worker():
    """Dedicated thread: always processes the LATEST frame, never a stale one."""
    global last_detection_time, motors_stopped
    global smooth_cx, smooth_cy, first_detection

    DW, DH = 320, 240
    _last_processed = None   # track last frame to skip duplicates
    _last_detect_t  = 0.0    # time of last detection run

    while True:
        now = time.monotonic()
        time_since = now - _last_detect_t

        # Rate-cap: sleep out the remainder of the interval if we're ahead
        if time_since < DETECT_INTERVAL:
            time.sleep(DETECT_INTERVAL - time_since)
            continue

        # Grab the LATEST frame — always fresh, never queued
        with _frame_lock:
            frame = _latest_frame

        if frame is None or frame is _last_processed:
            time.sleep(0.005)
            continue
        _last_processed  = frame
        _last_detect_t   = time.monotonic()

        detect_frame = cv2.resize(frame, (DW, DH))

        faces = detect_faces(detect_frame)

        if len(faces) == 0:
            continue

        scale_x = CAM_W / DW
        scale_y = CAM_H / DH

        # Face selection with lock-on
        # First detection: pick the largest high-confidence face.
        # Once locked: prefer the face closest to where we were last
        # tracking, with area as a tiebreaker. This stops the tracker
        # jumping to a different face just because it is momentarily
        # bigger — the main cause of confusion at close range.
        LOCK_WEIGHT = 4.0   # how strongly proximity beats size
        best = None
        best_rank = None
        for (fx, fy, fw, fh, fscore) in faces:
            if fscore < _conf_threshold:
                continue
            cx_n = (fx + fw / 2.0) / DW
            cy_n = (fy + fh / 2.0) / DH
            area_n = (fw * fh) / (DW * DH)
            if first_detection:
                rank = area_n * fscore
            else:
                dist = ((cx_n - smooth_cx) ** 2 + (cy_n - smooth_cy) ** 2) ** 0.5
                rank = area_n * fscore - LOCK_WEIGHT * dist
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best = (fx, fy, fw, fh, fscore, cx_n, cy_n)

        if best is None:
            continue

        bx, by, bw, bh, confidence, raw_cx, raw_cy = best
        bx = int(bx * scale_x); by = int(by * scale_y)
        bw = int(bw * scale_x); bh = int(bh * scale_y)

        last_detection_time = time.time()
        motors_stopped      = False

        if first_detection:
            smooth_cx = raw_cx
            smooth_cy = raw_cy
            first_detection = False

        # Lower SMOOTH_ALPHA = faster response; raise it if motors feel jittery
        smooth_cx = SMOOTH_ALPHA * raw_cx + (1 - SMOOTH_ALPHA) * smooth_cx
        smooth_cy = SMOOTH_ALPHA * raw_cy + (1 - SMOOTH_ALPHA) * smooth_cy

        px = pan_speed(smooth_cx - 0.5)
        ty = tilt_speed(smooth_cy - 0.5)

        try:
            Bridge.call("set_motors", px, ty)
        except Exception as e:
            print(f"[Bridge] {e}")



threading.Thread(target=_detection_worker, daemon=True).start()

# ── App loop ──────────────────────────────────────────────────────
def loop():
    global motors_stopped, first_detection, _detect_frame

    with _frame_lock:
        frame = _latest_frame

    if frame is not None:
        # Hand frame to detection thread only if it's a new frame
        with _detect_lock:
            if _detect_frame is not frame:
                _detect_frame = frame
                _detect_event.set()

    if not motors_stopped and (time.time() - last_detection_time) > LOST_TIMEOUT:
        try:
            Bridge.call("stop_motors")
        except Exception:
            pass
        motors_stopped  = True
        first_detection = True
        print("[TRACK] Face lost — motors stopped")

    time.sleep(0.01)

App.run(user_loop=loop)
