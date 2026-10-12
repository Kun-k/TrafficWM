#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
enter_docker_group "$@"
load_browser_env

install -d -m 0755 "$RUNTIME_ROOT/recordings"

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    docker stop --time 15 "$CONTAINER_NAME" >/dev/null
    docker container rm "$CONTAINER_NAME" >/dev/null
fi

docker run --detach \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --init \
    --pids-limit 512 \
    --cpus "${BROWSER_CPUS:-4}" \
    --memory "${BROWSER_MEMORY:-4g}" \
    --memory-swap "${BROWSER_MEMORY:-4g}" \
    --shm-size 1g \
    --publish 127.0.0.1:6901:6901 \
    --publish 127.0.0.1:9222:9223 \
    --add-host host.docker.internal:host-gateway \
    --env VNC_PW="$VNC_PASSWORD" \
    --env VNC_VIEW_ONLY_PW="${VNC_VIEW_ONLY_PASSWORD:-$VNC_PASSWORD}" \
    --env VNC_RESOLUTION="${BROWSER_RESOLUTION:-1280x720}" \
    --env MAX_FRAME_RATE="${BROWSER_MAX_FPS:-30}" \
    --env LAUNCH_URL="${BROWSER_LAUNCH_URL:-http://host.docker.internal:8890/}" \
    --env APP_ARGS="--start-maximized --window-size=1920,1080 --autoplay-policy=no-user-gesture-required --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-features=Translate,TranslateUI --disable-gpu --disable-gpu-rasterization --disable-software-rasterizer --remote-debugging-address=0.0.0.0 --remote-debugging-port=9222" \
    --env START_PULSEAUDIO=0 \
    --env KASM_SVC_AUDIO=0 \
    --env KASM_SVC_AUDIO_INPUT=0 \
    --env KASM_SVC_GAMEPAD=0 \
    --env KASM_SVC_PRINTER=0 \
    --env KASM_SVC_RECORDER=0 \
    --env KASM_SVC_UPLOADS=0 \
    --env KASM_SVC_WEBCAM=0 \
    --env TZ=Asia/Shanghai \
    --env RECORD_FPS="${RECORD_FPS:-30}" \
    --env RECORD_CRF="${RECORD_CRF:-22}" \
    --env RECORD_PRESET="${RECORD_PRESET:-veryfast}" \
    --env RECORD_THREADS="${RECORD_THREADS:-4}" \
    --env VNCOPTIONS="-PreferBandwidth -DynamicQualityMin=5 -DynamicQualityMax=8 -DLP_ClipDelay=0" \
    --mount "type=bind,src=$RUNTIME_ROOT/recordings,dst=/recordings" \
    --mount "type=bind,src=$SCRIPT_DIR/record.sh,dst=/usr/local/bin/trafficwm-record,readonly" \
    --mount "type=bind,src=$SCRIPT_DIR/cdp_proxy.py,dst=/usr/local/bin/trafficwm-cdp-proxy,readonly" \
    --mount "type=bind,src=$SCRIPT_DIR/kasmvnc.yaml,dst=/etc/kasmvnc/kasmvnc.yaml,readonly" \
    "${BROWSER_IMAGE:-docker.m.daocloud.io/kasmweb/chromium:1.17.0}"

for _ in $(seq 1 60); do
    if curl --noproxy '*' --insecure --silent --fail --max-time 2 \
        --user "kasm_user:$VNC_PASSWORD" https://127.0.0.1:6901/ >/dev/null; then
        docker exec --env DISPLAY=:1 "$CONTAINER_NAME" \
            xrandr --output VNC-0 --mode "${BROWSER_RESOLUTION:-1280x720}"
        docker exec --detach "$CONTAINER_NAME" \
            python3 /usr/local/bin/trafficwm-cdp-proxy \
                --listen-port 9223 --target-port 9222
        for _ in $(seq 1 30); do
            if curl --noproxy '*' --silent --fail --max-time 1 \
                http://127.0.0.1:9222/json/version >/dev/null; then
                break
            fi
            sleep 0.2
        done
        echo "TrafficWM browser is ready at https://127.0.0.1:6901"
        echo "Login user: kasm_user"
        exit 0
    fi
    sleep 1
done

docker logs --tail 100 "$CONTAINER_NAME" >&2
echo "Browser container did not become ready within 120 seconds." >&2
exit 1
