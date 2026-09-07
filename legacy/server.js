'use strict';
// ============================================================
// 屏幕识别 -> QQ 发送工具 · 本地服务（Node 零依赖）
// 功能：
//   - 托管 public/ 下的网页（前端做截屏 + OCR）
//   - GET  /api/status  返回服务与 QQ 运行/窗口状态
//   - POST /api/send    调用 qq-send.ps1 自动发送文本到 QQ 当前对话框
// 启动：node server.js（默认端口 8765，可用 PORT 环境变量修改）
// ============================================================
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = parseInt(process.env.PORT || '8765', 10);
const ROOT = __dirname;
const PUBLIC = path.join(ROOT, 'public');
const QQ_SEND_PS = path.join(ROOT, 'qq-send.ps1');
const QQ_LIST_PS = path.join(ROOT, 'qq-list.ps1');
const KEYWORDS_FILE = path.join(ROOT, 'keywords.txt');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
  '.gz': 'application/gzip',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.map': 'application/json'
};

// ---------------- 工具函数 ----------------
function safeJoin(base, rel) {
  const p = path.resolve(base, rel);
  if (p !== base && !p.startsWith(base + path.sep)) return null;
  return p;
}

// 读取 PowerShell 重定向的结果文件（兼容 UTF-8 / UTF-16 BOM）
function readResultFile(file) {
  try {
    const buf = fs.readFileSync(file);
    let str;
    if (buf.length >= 2 && buf[0] === 0xFF && buf[1] === 0xFE) str = buf.toString('utf16le', 2);
    else str = buf.toString('utf8');
    if (str.charCodeAt(0) === 0xFEFF) str = str.slice(1);
    return str;
  } catch (e) { return ''; }
}

// 从文本中提取第一个 JSON 对象
function extractJson(str) {
  const m = str.match(/\{[\s\S]*\}/);
  return m ? m[0] : '';
}

// 项目自有临时目录（任何环境都可写，避免 os.tmpdir() 在受限会话中不可写）
const TMPDIR = path.join(ROOT, 'tmp');
try { fs.mkdirSync(TMPDIR, { recursive: true }); } catch (e) {}
try {
  for (const f of fs.readdirSync(TMPDIR)) {
    if (f.startsWith('sqo-')) { try { fs.unlinkSync(path.join(TMPDIR, f)); } catch (e) {} }
  }
} catch (e) {}

// 直接 spawn powershell.exe（不经 cmd），结果文件路径由 -OutFile 参数传入 ps1 自行写入
function runPs(scriptPath, args, env, timeoutMs) {
  return new Promise((resolve) => {
    const outFile = path.join(TMPDIR, 'sqo-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '.json');
    const fullArgs = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptPath, '-OutFile', outFile]
      .concat(args || []);
    const child = spawn('powershell.exe', fullArgs, {
      env: Object.assign({}, process.env, env),
      windowsHide: true,
      stdio: ['ignore', 'ignore', 'pipe']
    });
    let errData = '';
    if (child.stderr) child.stderr.on('data', (d) => { errData += d; });
    const timer = setTimeout(() => { try { child.kill(); } catch (e) {} }, timeoutMs || 30000);
    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ code: -1, out: '', err: String(err && err.message || err), outFile: '' });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      const out = readResultFile(outFile);
      try { fs.unlinkSync(outFile); } catch (e) {}
      resolve({ code: code, out: out, err: errData, outFile: '' });
    });
  });
}

// ---------------- 状态（2 秒 TTL 缓存） ----------------
let statusCache = null;
let statusCacheAt = 0;

async function apiStatus() {
  const now = Date.now();
  if (statusCache && now - statusCacheAt < 2000) return statusCache;
  const base = { server: 'ok', qq: { running: false, windows: [] }, powerShell: 'ok' };
  try {
    const r = await runPs(QQ_LIST_PS, [], {}, 15000);
    if (r.code === 0 && r.out) {
      try {
        const parsed = JSON.parse(extractJson(r.out));
        if (parsed && parsed.ok === false) base.powerShell = parsed.detail || 'qq-list 脚本错误';
        else base.qq = parsed;
      } catch (e) { base.powerShell = '输出解析失败: ' + r.out.slice(0, 120); }
    } else if (r.code !== 0) {
      base.powerShell = '枚举失败(退出码 ' + r.code + '): ' + (r.err || r.out || '').slice(0, 200);
    }
  } catch (e) {
    base.powerShell = '调用失败: ' + e.message;
  }
  statusCache = base;
  statusCacheAt = now;
  return base;
}

// ---------------- 发送 ----------------
async function apiSend(body) {
  const text = String(body.text || '').trim();
  if (!text) return { ok: false, detail: '发送内容为空' };
  const key = body.key === 'ctrl_enter' ? 'ctrl_enter' : 'enter';
  const winFrag = String(body.window || 'auto').replace(/"/g, '').slice(0, 64) || 'auto';

  // 文本写入项目 tmp（UTF-8 BOM），规避命令行/环境变量编码问题
  const txtFile = path.join(TMPDIR, 'sqo-text-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '.txt');
  fs.writeFileSync(txtFile, '\uFEFF' + text, 'utf8');

  const r = await runPs(QQ_SEND_PS, ['-Key', key, '-Window', winFrag], { QQ_TEXT_FILE: txtFile }, 30000);
  try { fs.unlinkSync(txtFile); } catch (e) {}

  if (r.code !== 0 && !r.out) return { ok: false, detail: 'PowerShell 执行失败（退出码 ' + r.code + '）: ' + (r.err || '') };
  try {
    const parsed = JSON.parse(extractJson(r.out));
    return parsed && typeof parsed.ok === 'boolean' ? parsed : { ok: false, detail: '发送脚本输出异常' };
  } catch (e) {
    return { ok: false, detail: '解析发送结果失败: ' + r.out.slice(0, 200) };
  }
}

// ---------------- 发送截图（PNG base64 → QQ） ----------------
async function apiSendImage(body) {
  const b64 = String(body.image || '');
  if (!b64) return { ok: false, detail: '图片数据为空' };
  const key = body.key === 'ctrl_enter' ? 'ctrl_enter' : 'enter';
  const winFrag = String(body.window || 'auto').replace(/"/g, '').slice(0, 64) || 'auto';

  const imgFile = path.join(TMPDIR, 'sqo-img-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '.png');
  try {
    fs.writeFileSync(imgFile, Buffer.from(b64, 'base64'));
  } catch (e) {
    return { ok: false, detail: '图片数据解码失败: ' + e.message };
  }
  const r = await runPs(QQ_SEND_PS, ['-Key', key, '-Window', winFrag, '-ImageFile', imgFile], {}, 30000);
  try { fs.unlinkSync(imgFile); } catch (e) {}

  if (r.code !== 0 && !r.out) return { ok: false, detail: 'PowerShell 执行失败（退出码 ' + r.code + '）: ' + (r.err || '') };
  try {
    const parsed = JSON.parse(extractJson(r.out));
    return parsed && typeof parsed.ok === 'boolean' ? parsed : { ok: false, detail: '发送脚本输出异常' };
  } catch (e) {
    return { ok: false, detail: '解析发送结果失败: ' + r.out.slice(0, 200) };
  }
}

// ---------------- Windows 系统 OCR（备选识别引擎） ----------------
const OCR_WIN_PS = path.join(ROOT, 'ocr-win.ps1');

async function apiOcr(body) {
  const b64 = String(body.image || '');
  if (!b64) return { ok: false, detail: '图片数据为空' };
  const imgFile = path.join(TMPDIR, 'sqo-ocr-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '.png');
  try {
    fs.writeFileSync(imgFile, Buffer.from(b64, 'base64'));
  } catch (e) {
    return { ok: false, detail: '图片数据解码失败: ' + e.message };
  }
  const r = await runPs(OCR_WIN_PS, ['-ImagePath', imgFile], {}, 60000);
  try { fs.unlinkSync(imgFile); } catch (e) {}
  if (r.code !== 0 && !r.out) return { ok: false, detail: 'OCR 执行失败（退出码 ' + r.code + '）: ' + (r.err || '') };
  try {
    const parsed = JSON.parse(extractJson(r.out));
    return parsed && typeof parsed.ok === 'boolean'
      ? { ok: parsed.ok, text: parsed.text || '', lines: parsed.lines || [], detail: parsed.detail || '', ms: parsed.ms || 0 }
      : { ok: false, detail: 'OCR 输出异常' };
  } catch (e) {
    return { ok: false, detail: '解析 OCR 结果失败: ' + r.out.slice(0, 200) };
  }
}

// ---------------- HTTP ----------------
function sendJson(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

function readBody(req, limit) {
  return new Promise((resolve) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > (limit || 1024 * 1024)) { req.destroy(); resolve(null); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', () => resolve(null));
  });
}

function serveStatic(req, res) {
  const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
  const rel = urlPath === '/' ? 'index.html' : urlPath.replace(/^\/+/, '');
  const file = safeJoin(PUBLIC, rel);
  if (!file) { sendJson(res, 403, { error: 'forbidden' }); return; }
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) { sendJson(res, 404, { error: 'not found' }); return; }
    const ext = path.extname(file).toLowerCase();
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Content-Length': st.size,
      'Cache-Control': 'no-cache'   // 本地工具，禁用缓存避免浏览器跑到旧版 JS
    });
    fs.createReadStream(file).pipe(res);
  });
}

const server = http.createServer(async (req, res) => {
  const urlPath = (req.url || '/').split('?')[0];
  try {
    if (req.method === 'GET' && urlPath === '/api/health') { sendJson(res, 200, { ok: true }); return; }
    if (req.method === 'GET' && urlPath === '/api/status') { sendJson(res, 200, await apiStatus()); return; }
    // 关键词 txt 持久化
    if (req.method === 'GET' && urlPath === '/api/keywords') {
      let text = '', exists = false;
      try {
        if (fs.existsSync(KEYWORDS_FILE)) { text = fs.readFileSync(KEYWORDS_FILE, 'utf8'); exists = true; }
      } catch (e) { sendJson(res, 500, { ok: false, detail: '读取失败: ' + e.message }); return; }
      sendJson(res, 200, { ok: true, exists: exists, text: text });
      return;
    }
    if (req.method === 'POST' && urlPath === '/api/keywords') {
      const raw = await readBody(req);
      if (raw === null) { sendJson(res, 400, { ok: false, detail: '请求体过大或读取失败' }); return; }
      let body = {};
      try { body = JSON.parse(raw); } catch (e) { sendJson(res, 400, { ok: false, detail: '请求体不是合法 JSON' }); return; }
      const text = String(body.text || '');
      try {
        fs.writeFileSync(KEYWORDS_FILE, text, 'utf8');
        sendJson(res, 200, { ok: true, path: KEYWORDS_FILE });
      } catch (e) {
        sendJson(res, 200, { ok: false, detail: '写入失败: ' + e.message });
      }
      return;
    }
    if (req.method === 'POST' && urlPath === '/api/send') {
      const raw = await readBody(req);
      if (raw === null) { sendJson(res, 400, { ok: false, detail: '请求体过大或读取失败' }); return; }
      let body = {};
      try { body = JSON.parse(raw); } catch (e) { sendJson(res, 400, { ok: false, detail: '请求体不是合法 JSON' }); return; }
      sendJson(res, 200, await apiSend(body));
      return;
    }
    if (req.method === 'POST' && urlPath === '/api/send-image') {
      const raw = await readBody(req, 20 * 1024 * 1024);   // 截图 base64 可能较大
      if (raw === null) { sendJson(res, 400, { ok: false, detail: '请求体过大或读取失败' }); return; }
      let body = {};
      try { body = JSON.parse(raw); } catch (e) { sendJson(res, 400, { ok: false, detail: '请求体不是合法 JSON' }); return; }
      sendJson(res, 200, await apiSendImage(body));
      return;
    }
    if (req.method === 'POST' && urlPath === '/api/ocr') {
      const raw = await readBody(req, 20 * 1024 * 1024);
      if (raw === null) { sendJson(res, 400, { ok: false, detail: '请求体过大或读取失败' }); return; }
      let body = {};
      try { body = JSON.parse(raw); } catch (e) { sendJson(res, 400, { ok: false, detail: '请求体不是合法 JSON' }); return; }
      sendJson(res, 200, await apiOcr(body));
      return;
    }
    if (req.method === 'GET' || req.method === 'HEAD') { serveStatic(req, res); return; }
    sendJson(res, 405, { error: 'method not allowed' });
  } catch (e) {
    sendJson(res, 500, { error: 'internal error: ' + e.message });
  }
});

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    console.error('端口 ' + PORT + ' 已被占用。可设置环境变量 PORT=其他端口后重启，例如: set PORT=8899 && node server.js');
  } else {
    console.error('服务启动失败:', e.message);
  }
  process.exit(1);
});

server.listen(PORT, () => {
  console.log('[screen-qq-ocr] 服务已启动: http://127.0.0.1:' + PORT);
  console.log('[screen-qq-ocr] 按 Ctrl+C 停止');
  if (process.env.NO_AUTO_OPEN !== '1') {
    const url = 'http://127.0.0.1:' + PORT;
    try {
      const child = spawn('cmd.exe', ['/c', 'start', '', url], { stdio: 'ignore', windowsHide: true, detached: true });
      child.on('error', () => {});   // 打开浏览器失败不应影响服务器
      child.unref();
    } catch (e) {}
  }
});
