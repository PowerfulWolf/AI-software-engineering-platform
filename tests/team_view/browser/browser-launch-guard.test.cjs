const assert = require("node:assert/strict");
const {test} = require("node:test");
const {assertSafeBrowserLaunch} = require("./browser-launch-guard.cjs");

test("macOS system Chrome requires explicit isolated-host opt-in", () => {
  for (const channel of ["chrome", "chrome-beta", "chrome-dev", "chrome-canary", "msedge"]) {
    assert.throws(() => assertSafeBrowserLaunch({platform: "darwin", channel}),
      /Playwright system browser channels are disabled on macOS/);
  }
  assert.throws(() => assertSafeBrowserLaunch({platform: "darwin", channel: "chrome",
    allowSystemChrome: "true"}), /Playwright system browser channels are disabled on macOS/);
  assert.doesNotThrow(() => assertSafeBrowserLaunch({platform: "darwin", channel: "chrome",
    allowSystemChrome: "1"}));
});

test("Playwright bundled Chromium and non-macOS Chrome keep their normal behavior", () => {
  assert.doesNotThrow(() => assertSafeBrowserLaunch({platform: "darwin", channel: "chromium"}));
  assert.doesNotThrow(() => assertSafeBrowserLaunch({platform: "linux", channel: "chrome"}));
});
