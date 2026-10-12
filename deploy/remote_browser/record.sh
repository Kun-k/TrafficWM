#!/usr/bin/env bash
set -euo pipefail

PID_FILE=/tmp/trafficwm-record.pid
STATE_FILE=/tmp/trafficwm-record.state
LOG_FILE=/tmp/trafficwm-record.log
RECORDING_DIR=/recordings

recording_pid() {
    [[ -s "$PID_FILE" ]] || return 1
    local pid
    pid="$(cat "$PID_FILE")"
    kill -0 "$pid" 2>/dev/null || return 1
    local command
    command="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    [[ "$command" == *ffmpeg* && "$command" == *x11grab* ]] || return 1
    printf '%s' "$pid"
}

start_recording() {
    if pid="$(recording_pid)"; then
        echo "Recording is already active (pid=$pid)." >&2
        exit 1
    fi

    local name="${1:-trafficwm_$(date +%Y%m%d_%H%M%S)}"
    name="${name//[^A-Za-z0-9_.-]/_}"
    local resolution
    resolution="${RECORD_RESOLUTION:-${VNC_RESOLUTION:-}}"
    resolution="${resolution:-$(xdpyinfo -display "${DISPLAY:-:1}" | awk '/dimensions:/ {print $2; exit}')}"
    resolution="${resolution:-1280x720}"
    xrandr --display "${DISPLAY:-:1}" --output VNC-0 --mode "$resolution" >/dev/null 2>&1 || true
    local fps="${RECORD_FPS:-30}"
    local output="$RECORDING_DIR/$name.mp4"
    local partial="$RECORDING_DIR/.$name.partial.mp4"
    local video_filter=()
    if [[ "${RECORD_SHOW_CLOCK:-1}" != "0" ]]; then
        video_filter=(
            -vf
            "drawbox=x=iw-430:y=12:w=418:h=44:color=black@0.72:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf:fontcolor=white:fontsize=24:x=w-tw-22:y=21:text='%{localtime\\:%Y-%m-%d %H-%M-%S}'"
        )
    fi

    mkdir -p "$RECORDING_DIR"
    : >"$LOG_FILE"
    printf '%s\n%s\n' "$partial" "$output" >"$STATE_FILE"

    nohup ffmpeg -nostdin -hide_banner -loglevel warning -filter_threads 2 \
        -f x11grab -draw_mouse 1 -framerate "$fps" \
        -video_size "$resolution" -i "${DISPLAY:-:1}.0+0,0" \
        "${video_filter[@]}" \
        -an -c:v libx264 -threads "${RECORD_THREADS:-4}" \
        -preset "${RECORD_PRESET:-veryfast}" \
        -crf "${RECORD_CRF:-22}" -pix_fmt yuv420p \
        -movflags +faststart -y "$partial" \
        >>"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
    sleep 1

    if ! pid="$(recording_pid)"; then
        cat "$LOG_FILE" >&2
        echo "Recorder failed to start." >&2
        exit 1
    fi

    echo "Recording started: $output (pid=$pid, ${resolution}@${fps}fps)"
}

stop_recording() {
    if ! pid="$(recording_pid)"; then
        echo "No active recording."
        return
    fi

    kill -INT "$pid"
    for _ in $(seq 1 100); do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid"
    fi

    local partial output
    partial="$(sed -n '1p' "$STATE_FILE")"
    output="$(sed -n '2p' "$STATE_FILE")"
    if [[ -s "$partial" ]]; then
        mv "$partial" "$output"
        echo "Recording saved: $output"
    else
        cat "$LOG_FILE" >&2
        echo "Recording stopped without a valid output file." >&2
        exit 1
    fi
    : >"$PID_FILE"
}

show_status() {
    if pid="$(recording_pid)"; then
        local output
        output="$(sed -n '2p' "$STATE_FILE")"
        echo "recording=active pid=$pid output=$output"
    else
        echo "recording=inactive"
    fi
}

case "${1:-status}" in
    start) start_recording "${2:-}" ;;
    stop) stop_recording ;;
    status) show_status ;;
    *) echo "Usage: trafficwm-record {start [name]|stop|status}" >&2; exit 2 ;;
esac
