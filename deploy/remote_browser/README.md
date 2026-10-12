# TrafficWM Remote Browser

This deployment runs the official Kasm Chromium workspace as a single container.
Chromium reaches TrafficWM through Docker's host gateway, so simulation and video
traffic stay on the server. Only the compressed KasmVNC desktop stream crosses the
remote link.

## Runtime limits

- 6 CPU cores and 6 GiB RAM by default
- no GPU passthrough
- 1 GiB shared memory
- 1920x1080 at up to 30 FPS
- 4 KasmVNC rectangle-compression threads
- Chromium software GPU rasterization disabled (the server has no display GPU)
- PulseAudio disabled
- KasmVNC bound to host loopback only

## Start and stop

```bash
cd /mnt/rk/cnde/TrafficWM/deploy/remote_browser
./start.sh
./status.sh
./stop.sh
```

Open `https://127.0.0.1:6901` through an SSH local forward, or use the configured
Tailscale Serve URL. The standalone Kasm login name is `kasm_user`; passwords are
stored in the untracked `.env` file.

## Screen recording

The base image already includes FFmpeg. Recording uses X11 capture inside the
container and writes MP4 files directly to the large data disk.

```bash
./record-start.sh citynde_sparse
./record-stop.sh
ls -lh /mnt/rk/trafficwm-browser/recordings
```

Recording defaults are 30 FPS, H.264 CRF 22, the `veryfast` preset, and four
encoder threads. The explicit thread cap prevents FFmpeg from creating workers
for every host CPU inside the resource-limited container.

## Display benchmark

```bash
./benchmark.sh
KASM_URL=https://gpu-112.tailce82b9.ts.net:8443/ ./benchmark.sh
BENCHMARK_REMOTE_CLICK_X=640 BENCHMARK_REMOTE_CLICK_Y=400 \
  BENCHMARK_REMOTE_KEY=Space BENCHMARK_SCREENSHOT=/tmp/kasm.png ./benchmark.sh
```

The benchmark measures page and canvas readiness, browser animation cadence,
WebSocket traffic, and effective receive bandwidth through the same Kasm client
used by a remote browser.

The measured deployment and three-scenario validation results are recorded in
[`VALIDATION_20260820.md`](VALIDATION_20260820.md).
