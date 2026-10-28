function assertSafeBrowserLaunch({platform, channel, allowSystemChrome}) {
  if (platform === "darwin" && channel !== "chromium" && allowSystemChrome !== "1")
    throw new Error("Playwright system browser channels are disabled on macOS by default. " +
      "Use an isolated test host and set ASE_UI_ALLOW_SYSTEM_CHROME=1 explicitly before running browser tests.");
}

module.exports = {assertSafeBrowserLaunch};
