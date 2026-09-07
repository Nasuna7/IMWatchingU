'use strict';
// ============================================================
// 下载辅助脚本（Node/OpenSSL，规避本机 schannel TLS 异常）
// 用法: node download.js <输出目录> <url> [<url> ...]
// 每个文件写入 <输出目录>/<URL 文件名>，失败时退出码非 0
// ============================================================
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
const outDir = args[0];
const urls = args.slice(1);

function download(url, dest, redirects) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https:') ? https : http;
    const req = mod.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        if (redirects > 5) return reject(new Error('too many redirects: ' + url));
        return resolve(download(new URL(res.headers.location, url).href, dest, redirects + 1));
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error('HTTP ' + res.statusCode + ' for ' + url));
      }
      const tmp = dest + '.part';
      const out = fs.createWriteStream(tmp);
      res.pipe(out);
      out.on('finish', () => {
        out.close(() => { fs.renameSync(tmp, dest); resolve(dest); });
      });
      out.on('error', reject);
    });
    req.setTimeout(60000, () => req.destroy(new Error('timeout: ' + url)));
    req.on('error', reject);
  });
}

(async () => {
  if (!outDir || urls.length === 0) {
    console.error('用法: node download.js <输出目录> <url> [<url> ...]');
    process.exit(2);
  }
  fs.mkdirSync(outDir, { recursive: true });
  const jobs = urls.map((u) => {
    const name = path.basename(new URL(u).pathname);
    const dest = path.join(outDir, name);
    if (fs.existsSync(dest) && fs.statSync(dest).size > 0) {
      console.log('已存在，跳过: ' + name);
      return Promise.resolve();
    }
    return download(u, dest, 0).then(() => console.log('完成: ' + name));
  });
  const results = await Promise.allSettled(jobs);
  let fail = 0;
  for (const r of results) {
    if (r.status === 'rejected') { fail++; console.error('失败: ' + r.reason.message); }
  }
  process.exit(fail ? 1 : 0);
})();
