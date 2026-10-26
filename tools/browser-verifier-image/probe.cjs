const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const { chromium } = require('playwright');

async function socketDenied() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', (error) => resolve(error.code));
    server.listen(0, '127.0.0.1', () => {
      server.close();
      reject(new Error('loopback listener unexpectedly allowed'));
    });
  });
}

async function connectionDenied(host) {
  return await new Promise((resolve, reject) => {
    const socket = net.connect({host, port: 443});
    socket.once('error', (error) => resolve(error.code));
    socket.once('connect', () => {
      socket.destroy();
      reject(new Error('outbound connection unexpectedly allowed'));
    });
  });
}

(async () => {
  assert.equal(process.getuid(), 1001);
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.route('http://ui.test/**', (route) => route.fulfill({
      contentType: 'text/html',
      body: '<button onclick="this.textContent=42">go</button>',
    }));
    await page.goto('http://ui.test/');
    await page.getByRole('button', {name: 'go'}).click();
    assert.equal(await page.getByRole('button').innerText(), '42');
    const png = await page.screenshot();
    assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    console.log(`render_click_png=PASS bytes=${png.length}`);
  } finally {
    await browser.close();
  }
  const loopback = await socketDenied();
  assert.equal(loopback, 'EPERM');
  assert.equal(await connectionDenied('198.51.100.1'), 'EPERM');
  assert.equal(await connectionDenied('2001:db8::1'), 'EPERM');
  console.log(`loopback_listen=DENIED code=${loopback} outbound_ipv4=DENIED outbound_ipv6=DENIED`);
  assert.throws(() => fs.writeFileSync('/work/probe.cjs', 'mutated'), {code: 'EROFS'});
  assert.throws(() => fs.writeFileSync('/etc/ase-browser-probe', 'mutated'), {code: 'EROFS'});
  fs.writeFileSync('/tmp/ase-browser-probe', 'ok');
  console.log('probe_file_write=DENIED rootfs_write=DENIED scratch_write=PASS');
})().catch((error) => {console.error(error); process.exitCode = 1;});
