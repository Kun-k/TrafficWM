const { chromium } = require('@playwright/test');

const url = process.env.KASM_URL || 'https://127.0.0.1:6901/';
const username = process.env.KASM_USERNAME || 'kasm_user';
const password = process.env.VNC_PASSWORD;
const durationMs = Number(process.env.BENCHMARK_DURATION_MS || 10000);

if (!password) {
  throw new Error('VNC_PASSWORD is required');
}

async function main() {
  const browserArgs = ['--no-proxy-server'];
  if (process.env.KASM_HOST_IP) {
    browserArgs.push(`--host-resolver-rules=MAP ${new URL(url).hostname} ${process.env.KASM_HOST_IP}`);
  }
  const browser = await chromium.launch({ headless: true, args: browserArgs });
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      httpCredentials: { username, password },
      viewport: { width: 1280, height: 720 },
    });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    const latencyMs = Number(process.env.NETWORK_LATENCY_MS || 0);
    const networkMbps = Number(process.env.NETWORK_LIMIT_MBPS || 0);

  let receivedBytes = 0;
  let websocketPayloadBytes = 0;
  let websocketFrames = 0;
  let websocketCount = 0;
  await cdp.send('Network.enable');
  if (latencyMs > 0 || networkMbps > 0) {
    const bytesPerSecond = networkMbps > 0 ? (networkMbps * 1_000_000) / 8 : -1;
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: latencyMs,
      downloadThroughput: bytesPerSecond,
      uploadThroughput: bytesPerSecond,
      connectionType: 'wifi',
    });
  }
  cdp.on('Network.dataReceived', (event) => {
    receivedBytes += event.encodedDataLength || event.dataLength || 0;
  });
  cdp.on('Network.webSocketCreated', () => {
    websocketCount += 1;
  });
  cdp.on('Network.webSocketFrameReceived', (event) => {
    websocketFrames += 1;
    websocketPayloadBytes += event.response?.payloadData?.length || 0;
  });

  const startedAt = performance.now();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  const domContentLoadedMs = performance.now() - startedAt;
  await page.waitForFunction(
    () => [...document.querySelectorAll('canvas')].some((canvas) => (
      canvas.width >= 1024 && canvas.height >= 576 && canvas.clientWidth > 0 && canvas.clientHeight > 0
    )),
    null,
    { timeout: 30000 },
  );
  const canvasReadyMs = performance.now() - startedAt;

  const remoteClickX = Number(process.env.BENCHMARK_REMOTE_CLICK_X || 0);
  const remoteClickY = Number(process.env.BENCHMARK_REMOTE_CLICK_Y || 0);
  if (remoteClickX > 0 && remoteClickY > 0) {
    await page.mouse.click(remoteClickX, remoteClickY);
  }
  if (process.env.BENCHMARK_REMOTE_KEY) {
    await page.keyboard.press(process.env.BENCHMARK_REMOTE_KEY);
  }

  const raf = await page.evaluate(async (sampleMs) => {
    const source = [...document.querySelectorAll('canvas')].find((canvas) => (
      canvas.width >= 1024 && canvas.height >= 576 && canvas.clientWidth > 0
    ));
    const probe = document.createElement('canvas');
    probe.width = 64;
    probe.height = 36;
    const probeContext = probe.getContext('2d', { willReadFrequently: true });
    const begin = performance.now();
    let first = 0;
    let last = 0;
    let frames = 0;
    let lastHash = null;
    const visualChangeTimes = [];
    await new Promise((resolve) => {
      const tick = (timestamp) => {
        if (!first) first = timestamp;
        last = timestamp;
        frames += 1;
        if (source && probeContext) {
          probeContext.drawImage(source, 0, 0, probe.width, probe.height);
          const pixels = probeContext.getImageData(0, 0, probe.width, probe.height).data;
          let hash = 2166136261;
          for (let index = 0; index < pixels.length; index += 4) {
            hash ^= pixels[index] + (pixels[index + 1] << 8) + (pixels[index + 2] << 16);
            hash = Math.imul(hash, 16777619);
          }
          if (lastHash !== null && hash !== lastHash) visualChangeTimes.push(timestamp);
          lastHash = hash;
        }
        if (performance.now() - begin >= sampleMs) resolve();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    const elapsedSeconds = Math.max(0.001, (last - first) / 1000);
    const intervals = visualChangeTimes.slice(1).map((value, index) => value - visualChangeTimes[index]);
    intervals.sort((left, right) => left - right);
    const percentile = (values, ratio) => values.length
      ? values[Math.min(values.length - 1, Math.floor((values.length - 1) * ratio))]
      : null;
    return {
      frames,
      fps: (frames - 1) / elapsedSeconds,
      visualChanges: visualChangeTimes.length,
      visualChangeFps: visualChangeTimes.length / elapsedSeconds,
      visualChangeIntervalP50Ms: percentile(intervals, 0.5),
      visualChangeIntervalP95Ms: percentile(intervals, 0.95),
      visualProbeSupported: Boolean(source && probeContext),
    };
  }, durationMs);

  const pageState = await page.evaluate(() => ({
    title: document.title,
    canvases: [...document.querySelectorAll('canvas')].map((canvas) => ({
      width: canvas.width,
      height: canvas.height,
      clientWidth: canvas.clientWidth,
      clientHeight: canvas.clientHeight,
    })),
    videos: [...document.querySelectorAll('video')].map((video) => ({
      width: video.videoWidth,
      height: video.videoHeight,
      readyState: video.readyState,
    })),
  }));

  const elapsedSeconds = (performance.now() - startedAt) / 1000;
  const result = {
    url,
    emulated_latency_ms: latencyMs,
    emulated_limit_mbps: networkMbps,
    dom_content_loaded_ms: Number(domContentLoadedMs.toFixed(1)),
    canvas_ready_ms: Number(canvasReadyMs.toFixed(1)),
    sample_seconds: Number(elapsedSeconds.toFixed(3)),
    browser_raf_fps: Number(raf.fps.toFixed(2)),
    visual_change_fps: Number(raf.visualChangeFps.toFixed(2)),
    visual_change_count: raf.visualChanges,
    visual_change_interval_p50_ms: raf.visualChangeIntervalP50Ms == null
      ? null : Number(raf.visualChangeIntervalP50Ms.toFixed(2)),
    visual_change_interval_p95_ms: raf.visualChangeIntervalP95Ms == null
      ? null : Number(raf.visualChangeIntervalP95Ms.toFixed(2)),
    visual_probe_supported: raf.visualProbeSupported,
    network_received_mib: Number((receivedBytes / 1024 / 1024).toFixed(3)),
    network_mbps: Number(((receivedBytes * 8) / elapsedSeconds / 1_000_000).toFixed(3)),
    websocket_count: websocketCount,
    websocket_frames: websocketFrames,
    websocket_payload_mib: Number((websocketPayloadBytes / 1024 / 1024).toFixed(3)),
    page: pageState,
  };

  if (process.env.BENCHMARK_SCREENSHOT) {
    await page.screenshot({ path: process.env.BENCHMARK_SCREENSHOT });
  }

    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
