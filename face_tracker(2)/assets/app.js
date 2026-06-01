// Face Tracker Motor Controller — Frontend (Phone Camera Edition)
// Receives processed frames + detection events from Python via socket.io.

const socket = io(`http://${window.location.host}`);

// ── Phone camera preview (frames emitted by Python) ──────────────
(function startCameraPreview() {
  const wrap        = document.getElementById('cam-wrap');
  const placeholder = document.getElementById('cam-placeholder');

  const img = document.createElement('img');
  img.id = 'cam-img';
  img.style.cssText = 'width:100%;height:100%;object-fit:contain;background:#000;display:none;';
  img.alt = 'Camera feed';
  wrap.insertBefore(img, wrap.firstChild);

  socket.on('cam_frame', (msg) => {
    if (!msg || !msg.data) return;
    img.src = 'data:image/jpeg;base64,' + msg.data;
    if (img.style.display === 'none') {
      img.style.display = 'block';
      placeholder.style.display = 'none';
    }
  });
})();

// ── Socket status ────────────────────────────────────────────────
const dot        = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

socket.on('connect', () => {
  dot.className  = 'connected';
  statusText.textContent = 'connected — waiting for face…';
});
socket.on('disconnect', () => {
  dot.className  = '';
  statusText.textContent = 'disconnected';
});

// ── Detection event ──────────────────────────────────────────────
const faceDot  = document.getElementById('face-dot');
const panBar   = document.getElementById('pan-bar');
const tiltBar  = document.getElementById('tilt-bar');
const panVal   = document.getElementById('pan-val');
const tiltVal  = document.getElementById('tilt-val');
const dispConf = document.getElementById('disp-conf');
const dispPos  = document.getElementById('disp-pos');
const dispTime = document.getElementById('disp-time');

let lostTimer = null;

socket.on('detection', (msg) => {
  dot.className  = 'tracking';
  statusText.textContent = '🔴 tracking face';

  const cx = msg.cx ?? 0.5;
  const cy = msg.cy ?? 0.5;
  faceDot.style.left    = (cx * 100) + '%';
  faceDot.style.top     = (cy * 100) + '%';
  faceDot.style.display = 'block';

  setBar(panBar,  panVal,  msg.pan  ?? 0);
  setBar(tiltBar, tiltVal, msg.tilt ?? 0);

  const pct = msg.confidence ? Math.round(msg.confidence * 100) : 0;
  dispConf.textContent = pct + '%';
  dispPos.textContent  = `(${(cx).toFixed(2)}, ${(cy).toFixed(2)})`;
  dispTime.textContent = new Date(msg.timestamp).toLocaleTimeString();

  clearTimeout(lostTimer);
  lostTimer = setTimeout(onFaceLost, 1000);
});

socket.on('face_lost', onFaceLost);

function onFaceLost() {
  dot.className  = 'connected';
  statusText.textContent = 'connected — waiting for face…';
  faceDot.style.display = 'none';
  setBar(panBar,  panVal,  0);
  setBar(tiltBar, tiltVal, 0);
  dispConf.textContent = '—';
  dispPos.textContent  = '—';
}

function setBar(barEl, valEl, speed) {
  const pct = Math.abs(speed) / 100 * 50;
  barEl.style.width = pct + '%';
  barEl.classList.toggle('neg', speed < 0);
  valEl.textContent = (speed >= 0 ? '+' : '') + speed;
}

// ── Confidence slider ────────────────────────────────────────────
const slider  = document.getElementById('conf-slider');
const confVal = document.getElementById('conf-val');

slider.addEventListener('input', () => {
  const v = parseFloat(slider.value);
  confVal.textContent = v.toFixed(2);
  socket.emit('override_th', v);
});
