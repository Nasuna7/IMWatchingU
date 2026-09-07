'use strict';
/* ============================================================
 * 屏幕识别 -> QQ 发送工具 · 前端逻辑
 * 截屏(getDisplayMedia) + Tesseract.js 中文 OCR
 * + 关键词触发（每关键词条件+定制内容+保存/读取txt）
 * + 色块闪烁识别（250ms 采样，约500ms 周期持续≥2秒报警）
 * ============================================================ */
const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const el = {
  btnStart: $('#btnStart'), btnStop: $('#btnStop'), btnSnap: $('#btnSnap'),
  lowResCapture: $('#lowResCapture'),
  previewWrap: $('#previewWrap'), preview: $('#preview'), placeholder: $('#previewPlaceholder'),
  cropBox: $('#cropBox'), btnClearCrop: $('#btnClearCrop'),
  freq: $('#freq'), cooldown: $('#cooldown'), ocrRes: $('#ocrRes'), ocrEngine: $('#ocrEngine'),
  kwInput: $('#kwInput'), btnAddKw: $('#btnAddKw'), kwList: $('#kwList'),
  kwMinCount: $('#kwMinCount'), kwMsg: $('#kwMsg'),
  btnSaveKw: $('#btnSaveKw'), btnLoadKw: $('#btnLoadKw'),
  keyMode: $('#keyMode'), contentMode: $('#contentMode'), countdown: $('#countdown'), qqWindow: $('#qqWindow'),
  sendSnap: $('#sendSnap'), btnTestSnap: $('#btnTestSnap'),
  btnTestSend: $('#btnTestSend'), btnStartMonitor: $('#btnStartMonitor'), btnStopMonitor: $('#btnStopMonitor'),
  flashEnable: $('#flashEnable'), flashCooldown: $('#flashCooldown'), flashSound: $('#flashSound'),
  flashVerbose: $('#flashVerbose'), flashStatus: $('#flashStatus'),
  colorLog: $('#colorLog'),
  lastRecog: $('#lastRecog'), log: $('#log'),
  stServer: $('#stServer'), stQq: $('#stQq'), stOcr: $('#stOcr'),
  overlay: $('#countdownOverlay'), countdownNum: $('#countdownNum')
};

let worker = null;
let stream = null;
let capturing = false;
let monitoring = false;
let busy = false;
let timerId = null;
let crop = null;              // 归一化 {x,y,w,h}，null=全屏
let keywords = [];            // {kw:string, minCount:number(1=出现一次即触发), msg:string(空=默认内容)}
let condLogState = {};        // 关键词 -> 上次是否未达条件（用于只记一次日志）
let lastSent = {};            // 关键词 -> 上次发送时间戳（冷却）
let ocrLoaded = false;

let flashTimerId = null;      // 色块闪烁采样定时器（声明见闪烁模块内状态）

/* ---------------- 日志 ---------------- */
function log(msg, cls) {
  const t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const div = document.createElement('div');
  div.className = 'log-line' + (cls ? ' ' + cls : '');
  div.textContent = '[' + t + '] ' + msg;
  el.log.prepend(div);
  while (el.log.children.length > 300) el.log.lastChild.remove();
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/* ---------------- 警告音（Web Audio） ---------------- */
let audioCtx = null;

function ensureAudio() {
  if (!audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) { try { audioCtx = new AC(); } catch (e) { audioCtx = null; } }
  }
  if (audioCtx && audioCtx.state === 'suspended') { try { audioCtx.resume(); } catch (e) {} }
  return audioCtx;
}
document.addEventListener('click', () => ensureAudio());

function beep(freq, dur, delay) {
  if (!audioCtx) return;
  const t0 = audioCtx.currentTime + (delay || 0);
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = 'sine';
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(0.4, t0 + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.connect(gain); gain.connect(audioCtx.destination);
  osc.start(t0); osc.stop(t0 + dur + 0.05);
}
const SOUND_PATTERNS = {
  alarm:  () => { for (let i = 0; i < 3; i++) beep(880, 0.15, i * 0.22); },
  double: () => { beep(660, 0.12, 0); beep(660, 0.12, 0.18); },
  long:   () => beep(660, 0.6, 0),
  soft:   () => beep(440, 0.25, 0),
  none:   () => {}
};
function playSound(name) {
  ensureAudio();
  const fn = SOUND_PATTERNS[name];
  if (fn) fn();
}

// 持续播放报警音指定时长（按所选声音模式循环直到 durationMs 结束）
const SOUND_REPEAT_GAP = { alarm: 700, double: 450, long: 800, soft: 400, none: 0 };
function playAlarmDuration(soundName, durationMs) {
  ensureAudio();
  if (durationMs <= 0) return;
  const fn = SOUND_PATTERNS[soundName] || SOUND_PATTERNS.alarm;
  const gap = SOUND_REPEAT_GAP[soundName] || 700;
  if (gap <= 0) return;                       // none（静音）
  const start = Date.now();
  const step = () => {
    if (Date.now() - start >= durationMs) return;
    fn();
    setTimeout(step, gap);
  };
  step();
}

/* ---------------- 服务状态轮询 ---------------- */
let lastPsErr = '';

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    if (s.server === 'ok') {
      el.stServer.textContent = '服务: 正常';
      el.stServer.classList.remove('bad'); el.stServer.classList.add('good');
    } else {
      el.stServer.textContent = '服务: 异常';
      el.stServer.classList.remove('good'); el.stServer.classList.add('bad');
    }
    if (s.powerShell && s.powerShell !== 'ok') {
      if (s.powerShell !== lastPsErr) {
        lastPsErr = s.powerShell;
        log('状态检查: ' + s.powerShell, 'warn');
      }
    } else if (lastPsErr) {
      lastPsErr = '';
    }
    if (s.qq && s.qq.running) {
      el.stQq.textContent = 'QQ: 运行中';
      el.stQq.classList.remove('bad'); el.stQq.classList.add('good');
    } else {
      el.stQq.textContent = 'QQ: 未运行（请先启动并登录 QQ）';
      el.stQq.classList.remove('good'); el.stQq.classList.add('bad');
    }
    const wins = (s.qq && s.qq.windows) || [];
    const prev = el.qqWindow.value;
    const opts = wins.length
      ? wins.map((w) => '<option value="' + esc(w.title) + '">' + esc(w.title) + (w.visible ? '' : '（隐藏）') + '</option>').join('')
      : '<option value="">（无）</option>';
    el.qqWindow.innerHTML = '<option value="auto">自动（最合适的聊天窗口）</option>' + opts;
    if (Array.from(el.qqWindow.options).some((o) => o.value === prev)) el.qqWindow.value = prev;
  } catch (e) {
    el.stServer.textContent = '服务: 异常';
    el.stServer.classList.remove('good'); el.stServer.classList.add('bad');
  }
}

/* ---------------- OCR 引擎 ---------------- */
async function initOcr() {
  el.stOcr.textContent = 'OCR: 加载中…';
  try {
    worker = await Tesseract.createWorker('chi_sim', 1, {
      langPath: '/vendor/tessdata',
      workerPath: '/vendor/worker.min.js',
      corePath: '/vendor',
      logger: (m) => {
        if (m.status === 'loading tesseract core') el.stOcr.textContent = 'OCR: 加载内核…';
        else if (m.status === 'initializing tesseract') el.stOcr.textContent = 'OCR: 初始化…';
        else if (m.status === 'loading language traineddata') el.stOcr.textContent = 'OCR: 加载中文模型…';
        else if (m.status === 'initializing api') el.stOcr.textContent = 'OCR: 就绪';
      }
    });
    ocrLoaded = true;
    el.stOcr.textContent = 'OCR: 就绪 ✓';
    el.stOcr.classList.add('good');
    log('OCR 引擎加载完成（中文 chi_sim）');
  } catch (e) {
    el.stOcr.textContent = 'OCR: 加载失败';
    el.stOcr.classList.add('bad');
    log('OCR 引擎加载失败: ' + e, 'err');
  }
}

/* ---------------- 截屏 ---------------- */
async function startCapture() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
    log('当前浏览器不支持屏幕捕获（getDisplayMedia），请使用 Chrome/Edge', 'err');
    return;
  }
  try {
    // 帧率上限始终生效（识别每 2~10 秒才取一帧，高帧率纯属浪费）；
    // 勾选「低分辨率捕获」时整体限制在 1280×720，进一步减少解码开销
    const low = el.lowResCapture.checked;
    const videoConstraints = {
      displaySurface: 'monitor',
      frameRate: low ? { ideal: 5, max: 8 } : { ideal: 10, max: 15 }
    };
    if (low) {
      videoConstraints.width = { max: 1280 };
      videoConstraints.height = { max: 720 };
    }
    stream = await navigator.mediaDevices.getDisplayMedia({ video: videoConstraints, audio: false });
    capturing = true;
    el.preview.srcObject = stream;
    await el.preview.play().catch(() => {});
    el.previewWrap.classList.remove('hidden');
    el.placeholder.classList.add('hidden');
    el.btnStart.disabled = true;
    el.btnStop.disabled = false;
    el.btnSnap.disabled = false;
    el.btnTestSnap.disabled = false;
    updateMonitorGate();
    // 记录实际生效的捕获参数（便于确认降载是否生效）
    let resInfo = '';
    try {
      const s = stream.getVideoTracks()[0].getSettings();
      resInfo = '（实际 ' + s.width + '×' + s.height + ' @ ' + Math.round(s.frameRate || 0) + 'fps）';
    } catch (e) {}
    log('屏幕捕获已开始' + resInfo + (low ? ' [低分辨率模式]' : ''));
    stream.getVideoTracks()[0].addEventListener('ended', stopCapture);
  } catch (e) {
    log('未开始截屏: ' + (e && e.message ? e.message : e), 'err');
  }
}

function stopCapture() {
  stopMonitoring();
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  capturing = false;
  el.preview.srcObject = null;
  el.previewWrap.classList.add('hidden');
  el.placeholder.classList.remove('hidden');
  el.btnStart.disabled = false;
  el.btnStop.disabled = true;
  el.btnSnap.disabled = true;
  el.btnTestSnap.disabled = true;
  el.btnStartMonitor.disabled = true;
  el.btnStopMonitor.disabled = true;
  log('屏幕捕获已停止');
}

/* ---------------- 区域选择 ---------------- */
function videoBox() {
  const vw = el.preview.videoWidth, vh = el.preview.videoHeight;
  const ew = el.preview.clientWidth, eh = el.preview.clientHeight;
  if (!vw || !vh) return { x: 0, y: 0, w: ew, h: eh };
  const scale = Math.min(ew / vw, eh / vh);
  const dw = vw * scale, dh = vh * scale;
  return { x: (ew - dw) / 2, y: (eh - dh) / 2, w: dw, h: dh };
}

function posNorm(ev) {
  const box = videoBox();
  const rect = el.preview.getBoundingClientRect();
  const mx = ev.clientX - rect.left - box.x;
  const my = ev.clientY - rect.top - box.y;
  return { x: clamp(mx / box.w, 0, 1), y: clamp(my / box.h, 0, 1) };
}

let dragging = null;

el.preview.addEventListener('mousedown', (ev) => {
  if (!capturing) return;
  const p = posNorm(ev);
  dragging = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
  el.cropBox.classList.remove('hidden');
});
window.addEventListener('mousemove', (ev) => {
  if (!dragging) return;
  const p = posNorm(ev);
  dragging.x1 = p.x; dragging.y1 = p.y;
  renderCropBox();
});
window.addEventListener('mouseup', () => {
  if (!dragging) return;
  normalizeCrop();
  dragging = null;
  if (crop) {
    el.btnClearCrop.classList.remove('hidden');
    log('识别区域已设置: ' + Math.round(crop.w * 100) + '% × ' + Math.round(crop.h * 100) + '%（相对屏幕左上角）');
  }
});

function renderCropBox() {
  const box = videoBox();
  const x = Math.min(dragging.x0, dragging.x1), y = Math.min(dragging.y0, dragging.y1);
  const w = Math.abs(dragging.x1 - dragging.x0), h = Math.abs(dragging.y1 - dragging.y0);
  el.cropBox.style.left = (box.x + x * box.w) + 'px';
  el.cropBox.style.top = (box.y + y * box.h) + 'px';
  el.cropBox.style.width = (w * box.w) + 'px';
  el.cropBox.style.height = (h * box.h) + 'px';
}

function normalizeCrop() {
  const x = Math.min(dragging.x0, dragging.x1), y = Math.min(dragging.y0, dragging.y1);
  const w = Math.abs(dragging.x1 - dragging.x0), h = Math.abs(dragging.y1 - dragging.y0);
  if (w < 0.01 || h < 0.01) {
    crop = null;
    el.cropBox.classList.add('hidden');
    el.btnClearCrop.classList.add('hidden');
    return;
  }
  crop = { x: x, y: y, w: w, h: h };
}

el.btnClearCrop.addEventListener('click', () => {
  crop = null;
  el.cropBox.classList.add('hidden');
  el.btnClearCrop.classList.add('hidden');
  log('已清除区域，改为全屏识别');
});

/* ---------------- 取帧 + 识别处理 ---------------- */
function captureCanvas() {
  const vw = el.preview.videoWidth, vh = el.preview.videoHeight;
  if (!vw || !vh) return null;
  const rect = crop || { x: 0, y: 0, w: 1, h: 1 };
  const sx = rect.x * vw, sy = rect.y * vh;
  const sw = Math.max(1, rect.w * vw), sh = Math.max(1, rect.h * vh);
  const MAXW = parseInt(el.ocrRes.value || '1920', 10) || 1920;   // OCR 分辨率可调：1280/1920/2560
  const scale = Math.min(1, MAXW / sw);
  const outW = Math.max(1, Math.round(sw * scale));
  const outH = Math.max(1, Math.round(sh * scale));
  const c = document.createElement('canvas');
  c.width = outW; c.height = outH;
  c.getContext('2d').drawImage(el.preview, sx, sy, sw, sh, 0, 0, outW, outH);
  return c;
}

// OCR 预处理：小区域自动放大 2 倍 + 灰度化 + 对比度拉伸（暗色背景自动反色为黑字白底）
// 返回新画布，不影响原始画布（色块识别仍用原图取色）
function preprocessForOcr(c) {
  const w = c.width, h = c.height;
  const scale = w < 900 ? 2 : 1;                    // 小区域放大，提升小字识别
  const out = document.createElement('canvas');
  out.width = Math.round(w * scale);
  out.height = Math.round(h * scale);
  const octx = out.getContext('2d');
  octx.imageSmoothingEnabled = true;
  octx.imageSmoothingQuality = 'high';
  octx.drawImage(c, 0, 0, out.width, out.height);
  let img;
  try { img = octx.getImageData(0, 0, out.width, out.height); } catch (e) { return out; }
  const d = img.data;
  const n = out.width * out.height;
  // 灰度直方图 + 亮度均值（一次遍历）
  const hist = new Uint32Array(256);
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    const g = (d[p] * 299 + d[p + 1] * 587 + d[p + 2] * 114) / 1000 | 0;
    hist[g]++;
    sum += g;
  }
  // 1% / 99% 百分位（抗噪的对比度拉伸范围）
  let cum = 0, lo = 0, hi = 255;
  for (let v = 0; v < 256; v++) { cum += hist[v]; if (cum >= n * 0.01) { lo = v; break; } }
  cum = 0;
  for (let v = 255; v >= 0; v--) { cum += hist[v]; if (cum >= n * 0.01) { hi = v; break; } }
  if (hi - lo < 10) { lo = Math.max(0, lo - 5); hi = Math.min(255, hi + 5); }
  const range = (hi - lo) || 1;
  // 反色判定：比较暗/亮两侧像素数量，背景（占多数的一侧）偏暗才反色为黑字白底
  const mid = (lo + hi) / 2;
  let darkCount = 0, lightCount = 0;
  for (let v = 0; v < 256; v++) {
    if (v <= mid) darkCount += hist[v]; else lightCount += hist[v];
  }
  const invert = darkCount > lightCount;
  const map = new Uint8Array(256);
  for (let v = 0; v < 256; v++) {
    let g = (v - lo) / range * 255;
    if (invert) g = 255 - g;
    map[v] = g < 0 ? 0 : (g > 255 ? 255 : (g | 0));
  }
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    const g = map[(d[p] * 299 + d[p + 1] * 587 + d[p + 2] * 114) / 1000 | 0];
    d[p] = g; d[p + 1] = g; d[p + 2] = g;
  }
  octx.putImageData(img, 0, 0);
  return out;
}

function showRecog(text, data, lineCount, charCount) {
  const clean = (text || '').trim();
  el.lastRecog.textContent = clean
    ? clean.replace(/\n/g, ' ⏎ ').slice(0, 200) + '  [' + lineCount + '行/' + charCount + '字]'
    : '(未识别到文字)';
  if (clean) log('识别: ' + clean.replace(/\n/g, ' ⏎ ').slice(0, 120) + '（' + lineCount + '行）');
  return { text: clean, norm: clean.replace(/\s+/g, ''), data: data, lineCount: lineCount };
}

// 统一处理一次识别结果（监控循环与手动识别共用）
async function processRecognition(c, data) {
  const raw = (data && data.text) || '';
  const lines = (data && data.lines) || [];
  const lineCount = lines.length;
  const charCount = raw.replace(/\s+/g, '').length;

  if (!raw.trim()) {
    el.lastRecog.textContent = '(未识别到文字)';
    return;
  }
  const shown = showRecog(raw, data, lineCount, charCount);
  if (monitoring) {
    await checkKeywords(shown.norm, shown.text, data, shown.lineCount, c);
  }
}

// 按所选引擎识别（tesseract 浏览器本地 / winocr 走服务器 Windows OCR）
async function recognizeCanvas(c) {
  const eng = el.ocrEngine.value;
  if (eng === 'winocr') {
    let b64 = '';
    try { b64 = c.toDataURL('image/png').split(',')[1] || ''; } catch (e) { throw new Error('截图编码失败: ' + e); }
    const r = await fetch('/api/ocr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: b64 })
    });
    const res = await r.json();
    if (!res.ok) throw new Error(res.detail || 'Windows OCR 失败');
    return { data: { text: res.text || '', lines: (res.lines || []).map((l) => ({ text: l.text })) } };
  }
  const r = await worker.recognize(preprocessForOcr(c));
  return r;
}

async function snapOnce() {
  if (!capturing) { log('请先开始截屏', 'err'); return; }
  if (!ocrLoaded) { log('OCR 引擎尚未就绪，请稍候', 'err'); return; }
  try {
    const c = captureCanvas();
    if (!c) { log('画面尚未就绪', 'warn'); return; }
    const r = await recognizeCanvas(c);
    await processRecognition(c, r.data);
  } catch (e) {
    log('识别失败: ' + e, 'err');
  }
}

/* ---------------- 监控循环（含自动暂停，避免后台占用 CPU） ---------------- */
let hiddenPaused = false;    // 标签页被隐藏 → 完全暂停，返回时自动恢复

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    // 标签页被切走：暂停全部监控工作，避免后台全速 OCR 拖慢系统
    if (monitoring) {
      monitoring = false;
      clearTimeout(timerId);
      stopFlashSampler();
      hiddenPaused = true;
      el.btnStopMonitor.disabled = true;
      el.btnStartMonitor.disabled = true;
      try { el.preview.pause(); } catch (e) {}
      log('⏸ 页面已隐藏，监控暂停；回到本页面自动继续', 'warn');
    }
  } else {
    try { el.preview.play().catch(() => {}); } catch (e) {}
    if (hiddenPaused) {
      hiddenPaused = false;
      if (capturing && canMonitorNow()) {
        monitoring = true;
        el.btnStartMonitor.disabled = true;
        el.btnStopMonitor.disabled = false;
        log('▶ 页面已恢复，监控继续', 'warn');
        startFlashSampler();
        monitorTick();
      } else {
        updateMonitorGate();
      }
    }
  }
});

function scheduleNext() {
  if (!monitoring) return;
  clearTimeout(timerId);
  timerId = setTimeout(monitorTick, parseInt(el.freq.value, 10));
}

async function monitorTick() {
  if (!monitoring) return;
  if (busy || !capturing || !worker) { scheduleNext(); return; }
  busy = true;
  try {
    const c = captureCanvas();
    if (c) {
      const r = await recognizeCanvas(c);
      await processRecognition(c, r.data);
    }
  } catch (e) {
    // 单帧失败忽略，下一轮继续
  } finally {
    busy = false;
    scheduleNext();
  }
}

/* ---------------- 关键词触发（每关键词：出现次数条件 + 定制消息） ---------------- */
function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 统计关键词在归一化文本中出现的次数（非重叠匹配）
function countOccurrences(text, kw) {
  if (!kw) return 0;
  const m = text.match(new RegExp(escapeRegExp(kw), 'g'));
  return m ? m.length : 0;
}

async function checkKeywords(norm, rawText, data, lineCount, canvas) {
  const now = Date.now();
  const cd = Math.max(0, parseInt(el.cooldown.value || '0', 10)) * 1000;
  for (const item of keywords) {
    const k = item.kw.replace(/\s+/g, '');
    if (!k) continue;
    const occurs = countOccurrences(norm, k);
    if (occurs < 1) continue;
    // 监控条件：关键词本身出现 ≥N 次才触发（仅状态变化时记一次日志，避免刷屏）
    if (item.minCount > 1 && occurs < item.minCount) {
      if (!condLogState[k]) {
        condLogState[k] = true;
        log('⏳ 关键词「' + item.kw + '」出现 ' + occurs + ' 次，未达条件（需 ≥' + item.minCount + ' 次）', 'warn');
      }
      continue;
    }
    condLogState[k] = false;
    if (lastSent[k] && now - lastSent[k] < cd) continue;   // 冷却中
    // 发送内容：关键词定制消息 > 默认（命中行/全文）
    const sendText = item.msg !== '' ? item.msg : buildSendText(k, rawText, data);
    lastSent[k] = now;
    const tag = item.msg !== '' ? '（定制消息）' : (item.minCount > 1 ? '（出现≥' + item.minCount + '次）' : '');
    log('🎯 命中关键词「' + item.kw + '」（出现 ' + occurs + ' 次）' + tag + ' → 发送: ' + sendText.replace(/\n/g, ' ⏎ ').slice(0, 80), 'hit');
    // 串行发送：先等文字发送完成，再发截图（并发会互相抢 QQ 焦点和剪贴板导致文字丢失）
    await doSendWithCountdown(sendText);
    if (el.sendSnap.checked && canvas) {
      await sendSnapImage(canvas, true);   // 截图不再单独倒计时
    }
  }
}

function buildSendText(kw, rawText, data) {
  if (el.contentMode.value === 'full') return rawText.trim();
  const lines = (data && data.lines) ? data.lines.map((l) => l.text) : rawText.split('\n');
  const hit = lines.find((l) => l.replace(/\s+/g, '').includes(kw));
  return (hit || rawText).trim();
}

async function doSendWithCountdown(text) {
  const cd = parseInt(el.countdown.value || '0', 10);
  if (cd > 0) {
    el.overlay.classList.remove('hidden');
    let cancelled = false;
    for (let i = cd; i > 0; i--) {
      el.countdownNum.textContent = String(i);
      await new Promise((r) => setTimeout(r, 1000));
      if (!monitoring) { cancelled = true; break; }
    }
    el.overlay.classList.add('hidden');
    if (cancelled) { log('监控已停止/暂停，取消本次发送', 'warn'); return; }
  }
  if (!monitoring) { log('监控已暂停，取消发送', 'warn'); return; }
  await doSend(text);
}

async function doSend(text) {
  const key = el.keyMode.value;
  const win = el.qqWindow.value;
  log('发送到 QQ（窗口: ' + (win === 'auto' ? '自动' : win) + '，按键: ' + key + '）: ' + text.replace(/\n/g, ' ⏎ ').slice(0, 100));
  try {
    const r = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, key: key, window: win })
    });
    const res = await r.json();
    if (res.ok) log('✅ 发送成功: ' + res.detail, 'ok');
    else log('❌ 发送失败: ' + res.detail, 'err');
  } catch (e) {
    log('❌ 发送请求异常: ' + e, 'err');
  }
}

// 把识别区域截图发送到 QQ（PNG → base64 → 服务器 → 剪贴板图片 → 粘贴发送）
// skipCountdown=true 时不再单独倒计时（关键词流程中文字已倒计时过，串行衔接）
async function sendSnapImage(canvas, skipCountdown) {
  if (!canvas) { log('截图失败：画面未就绪', 'err'); return; }
  if (monitoring === false && !capturing) { log('监控未运行，取消截图发送', 'warn'); return; }
  const cd = parseInt(el.countdown.value || '0', 10);
  if (cd > 0 && !skipCountdown) {
    el.overlay.classList.remove('hidden');
    let cancelled = false;
    for (let i = cd; i > 0; i--) {
      el.countdownNum.textContent = String(i);
      await new Promise((r) => setTimeout(r, 1000));
      if (!monitoring) { cancelled = true; break; }
    }
    el.overlay.classList.add('hidden');
    if (cancelled) { log('监控已停止/暂停，取消截图发送', 'warn'); return; }
  }
  let b64 = '';
  try {
    b64 = canvas.toDataURL('image/png').split(',')[1] || '';
  } catch (e) {
    log('❌ 截图编码失败: ' + e, 'err');
    return;
  }
  if (!b64) { log('❌ 截图编码为空', 'err'); return; }
  const key = el.keyMode.value;
  const win = el.qqWindow.value;
  log('发送识别区域截图到 QQ（' + Math.round(b64.length * 3 / 4 / 1024) + ' KB）…');
  try {
    const r = await fetch('/api/send-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: b64, key: key, window: win })
    });
    const res = await r.json();
    if (res.ok) log('✅ 截图发送成功: ' + res.detail, 'ok');
    else log('❌ 截图发送失败: ' + res.detail, 'err');
  } catch (e) {
    log('❌ 截图发送请求异常: ' + e, 'err');
  }
}

/* ---------------- 关键词管理 ---------------- */
function addKeyword() {
  const v = el.kwInput.value.trim();
  if (!v) { log('请输入关键词', 'warn'); return; }
  if (keywords.some((x) => x.kw === v)) { log('关键词已存在: ' + v, 'warn'); return; }
  const minCount = Math.max(1, parseInt(el.kwMinCount.value || '1', 10) || 1);
  const msg = el.kwMsg.value.trim();
  keywords.push({ kw: v, minCount: minCount, msg: msg });
  el.kwInput.value = '';
  el.kwMsg.value = '';
  renderKwList();
  updateMonitorGate();
  log('已添加关键词: ' + v + (minCount > 1 ? '（出现≥' + minCount + '次才触发）' : '') + (msg ? ' → ' + msg.slice(0, 30) : ''));
}

function removeKeyword(k) {
  keywords = keywords.filter((x) => x.kw !== k);
  delete lastSent[k];
  delete condLogState[k];
  renderKwList();
  updateMonitorGate();
  log('已删除关键词: ' + k);
}

function renderKwList() {
  el.kwList.innerHTML = keywords.map((x) =>
    '<span class="kw-chip">' + esc(x.kw) +
    (x.minCount > 1 ? ' <b style="color:#b3541e">出现≥' + x.minCount + '次</b>' : '') +
    (x.msg ? ' → ' + esc(x.msg.slice(0, 24)) : '') +
    ' <button class="kw-del" data-kw="' + esc(x.kw) + '">×</button></span>'
  ).join('');
  $$('.kw-del').forEach((b) => b.addEventListener('click', () => removeKeyword(b.dataset.kw)));
}



/* ---------------- 色块闪烁识别（250ms 采样，连续4次变化 → 3秒持续报警） ---------------- */
const FLASH_SAMPLE_MS = 250;      // 采样间隔
const FLASH_TRIGGER_RUN = 4;      // 连续 N 次采样颜色变化即触发
const FLASH_ALARM_MS = 3000;      // 报警音持续时长

// 像素分类：只认 红/白/橙，其他忽略
function classifyBlockColor(r, g, b) {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  const sat = mx === 0 ? 0 : (mx - mn) / mx;
  if (mx < 60) return null;                                      // 深色像素（深色背景）忽略
  if (r > 205 && g > 205 && b > 205 && sat < 0.3) return '白';
  if (sat < 0.25) return null;
  const d = mx - mn;
  let h;
  if (mx === r) h = ((g - b) / d) % 6;
  else if (mx === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  if (h < 18 || h >= 342) return '红';
  if (h < 55) return '橙';
  return null;
}

// 轻量取帧：识别区域的 1/4 分辨率小图（250ms 一次，必须快）
function captureCanvasLight() {
  const vw = el.preview.videoWidth, vh = el.preview.videoHeight;
  if (!vw || !vh) return null;
  const rect = crop || { x: 0, y: 0, w: 1, h: 1 };
  const sw = Math.max(2, rect.w * vw), sh = Math.max(2, rect.h * vh);
  const outW = Math.max(4, Math.round(sw / 4));
  const outH = Math.max(4, Math.round(sh / 4));
  const c = document.createElement('canvas');
  c.width = outW; c.height = outH;
  c.getContext('2d').drawImage(el.preview, rect.x * vw, rect.y * vh, sw, sh, 0, 0, outW, outH);
  return c;
}

// 统计小图中 红/白/橙 数量最多的颜色（无/深色背景 → null）
function dominantBlockColor(canvas) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  let img;
  try { img = ctx.getImageData(0, 0, W, H).data; } catch (e) { return null; }
  const counts = { '红': 0, '白': 0, '橙': 0 };
  for (let p = 0; p < img.length; p += 8) {   // 每 2 像素采样一次
    const name = classifyBlockColor(img[p], img[p + 1], img[p + 2]);
    if (name) counts[name]++;
  }
  const total = counts['红'] + counts['白'] + counts['橙'];
  if (total === 0) return null;
  let best = '红';
  if (counts['橙'] > counts[best]) best = '橙';
  if (counts['白'] > counts[best]) best = '白';
  return best;
}

// 色块专用日志（追加到 ④ 卡片内的独立日志区）
function colorLogLine(msg, cls) {
  if (!el.colorLog) return;
  const t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const div = document.createElement('div');
  div.className = 'log-line' + (cls ? ' ' + cls : '');
  div.textContent = '[' + t + '] ' + msg;
  el.colorLog.prepend(div);
  while (el.colorLog.children.length > 80) el.colorLog.lastChild.remove();
}

let lastSampleState = undefined;  // 上一次采样状态（用于连续性判断）
let consecChanges = 0;            // 连续变化采样计数
let flashAlarmAt = 0;             // 上次报警时间戳
let flashWarned = false;          // 采样启动提示只记一次

// 单次采样 tick（250ms）
function flashSampleTick() {
  if (!monitoring || !el.flashEnable.checked || !capturing) { stopFlashSampler(); return; }
  const c = captureCanvasLight();
  if (!c) return;
  const state = dominantBlockColor(c);
  const now = Date.now();

  // 连续变化计数：本次与上次采样不同则 +1，相同则清零
  const prev = lastSampleState;
  if (prev !== undefined) {
    if (state !== prev) {
      consecChanges++;
    } else {
      if (consecChanges >= FLASH_TRIGGER_RUN) {
        colorLogLine('连续变化中断（颜色稳定），计数清零', '');
      }
      consecChanges = 0;
    }
  } else {
    consecChanges = 0;
  }
  lastSampleState = state;

  // 详细日志：状态变化时记录
  if (el.flashVerbose.checked && prev !== undefined && state !== prev) {
    colorLogLine('状态: ' + (prev || '无') + ' → ' + (state || '无') + '（连续变化 ' + consecChanges + '/' + FLASH_TRIGGER_RUN + '）', '');
  }

  // 连续 4 次采样颜色变化 → 触发持续 3 秒报警（按报警冷却间隔可重复触发）
  if (consecChanges >= FLASH_TRIGGER_RUN) {
    const cd = Math.max(0, parseInt(el.flashCooldown.value || '0', 10)) * 1000;
    if (now - flashAlarmAt >= cd) {
      flashAlarmAt = now;
      playAlarmDuration(el.flashSound.value, FLASH_ALARM_MS);
      log('🚨 颜色连续变化 ' + consecChanges + ' 次（250ms 采样）→ 持续 3 秒报警', 'err');
      colorLogLine('触发报警：连续 ' + consecChanges + ' 次采样颜色变化 → ' + (FLASH_ALARM_MS / 1000) + ' 秒持续报警音', 'err');
    }
  }
  el.flashStatus.innerHTML = consecChanges >= FLASH_TRIGGER_RUN
    ? '当前：<b>🚨 报警中</b>（连续 ' + consecChanges + ' 次变化）'
    : '当前：色块 ' + (state || '无') + '（连续变化 ' + consecChanges + '/' + FLASH_TRIGGER_RUN + '）';
}

function startFlashSampler() {
  stopFlashSampler();
  lastSampleState = undefined;
  consecChanges = 0;
  if (!el.flashEnable.checked) return;
  if (!flashWarned) {
    flashWarned = true;
    colorLogLine('闪烁监控已启动：250ms 采样，连续 ' + FLASH_TRIGGER_RUN + ' 次颜色变化 → ' + (FLASH_ALARM_MS / 1000) + ' 秒持续报警', '');
  }
  flashTimerId = setInterval(flashSampleTick, FLASH_SAMPLE_MS);
}

function stopFlashSampler() {
  if (flashTimerId) { clearInterval(flashTimerId); flashTimerId = null; }
}

/* ---------------- 关键词 保存/读取 txt ---------------- */

/* ---------------- 关键词 保存/读取 txt ---------------- */


/* ---------------- 关键词 保存/读取 txt ---------------- */
async function saveKeywords() {
  const text = keywords.map((k) => k.kw + '|' + (k.minCount || 1) + '|' + (k.msg || '')).join('\n');
  try {
    const r = await fetch('/api/keywords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    });
    const res = await r.json();
    if (res.ok) log('💾 关键词已保存到 keywords.txt（' + keywords.length + ' 条）', 'ok');
    else log('❌ 保存失败: ' + (res.detail || ''), 'err');
  } catch (e) {
    log('❌ 保存请求异常: ' + e, 'err');
  }
}

async function loadKeywords() {
  try {
    const r = await fetch('/api/keywords');
    const res = await r.json();
    if (!res.ok) { log('❌ 读取失败: ' + (res.detail || ''), 'err'); return; }
    if (!res.exists || !res.text.trim()) { log('keywords.txt 不存在或为空', 'warn'); return; }
    const loaded = [];
    for (const line of res.text.split(/\r?\n/)) {
      const s = line.trim();
      if (!s) continue;
      const parts = s.split('|');
      loaded.push({
        kw: (parts[0] || '').trim(),
        minCount: Math.max(1, parseInt(parts[1], 10) || 1),
        msg: (parts[2] || '').trim()
      });
    }
    const valid = loaded.filter((x) => x.kw);
    keywords = valid;
    renderKwList();
    updateMonitorGate();
    log('📂 已从 keywords.txt 读取 ' + valid.length + ' 条关键词', 'ok');
  } catch (e) {
    log('❌ 读取请求异常: ' + e, 'err');
  }
}

/* ---------------- 监控开关 ---------------- */
function canMonitorNow() {
  return capturing && (
    keywords.length > 0 ||
    el.flashEnable.checked
  );
}

function updateMonitorGate() {
  el.btnStartMonitor.disabled = !canMonitorNow();
}

function startMonitor() {
  if (!capturing) { log('请先开始截屏', 'err'); return; }
  if (!keywords.length && !el.flashEnable.checked) {
    log('请先添加关键词，或启用色块闪烁识别模块', 'err');
    return;
  }
  if (!ocrLoaded) { log('OCR 引擎尚未就绪，请稍候', 'err'); return; }
  ensureAudio();
  monitoring = true;
  el.btnStartMonitor.disabled = true;
  el.btnStopMonitor.disabled = false;
  log('🚀 开始监控（频率 ' + (parseInt(el.freq.value, 10) / 1000) + 's，关键词 ' + keywords.length + ' 个，色块闪烁 ' +
    (el.flashEnable.checked ? '开' : '关') + '）');
  startFlashSampler();
  monitorTick();
}

function stopMonitoring() {
  const was = monitoring;
  monitoring = false;
  clearTimeout(timerId);
  stopFlashSampler();
  if (was) {
    updateMonitorGate();
    el.btnStopMonitor.disabled = true;
    log('⏹ 监控已停止');
  }
  return was;
}

/* ---------------- 事件绑定 ---------------- */
el.btnStart.addEventListener('click', startCapture);
el.btnStop.addEventListener('click', stopCapture);
el.btnSnap.addEventListener('click', snapOnce);
el.kwInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addKeyword(); } });
el.btnAddKw.addEventListener('click', addKeyword);
el.btnSaveKw.addEventListener('click', saveKeywords);
el.btnLoadKw.addEventListener('click', loadKeywords);
el.flashEnable.addEventListener('change', () => {
  updateMonitorGate();
  if (el.flashEnable.checked) {
    el.flashStatus.textContent = '当前：未检测（开始监控后启动 250ms 采样）';
  } else {
    el.flashStatus.textContent = '当前：未检测';
    if (!monitoring) stopFlashSampler();
  }
});
el.btnTestSend.addEventListener('click', () => {
  doSend('【屏幕识别工具】测试消息：链路正常 ✓ ' + new Date().toLocaleTimeString('zh-CN', { hour12: false }));
});
el.btnTestSnap.addEventListener('click', () => {
  if (!capturing) { log('请先开始截屏', 'err'); return; }
  const c = captureCanvas();
  if (!c) { log('画面尚未就绪', 'warn'); return; }
  sendSnapImage(c);
});
el.btnStartMonitor.addEventListener('click', startMonitor);
el.btnStopMonitor.addEventListener('click', () => stopMonitoring());

/* ---------------- 初始化 ---------------- */
log('前端 v21 已加载（色块闪烁 500ms×2s 检测 / 关键词出现次数）');
initOcr();
refreshStatus();
setInterval(refreshStatus, 3000);
