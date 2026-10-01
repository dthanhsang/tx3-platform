#!/system/bin/sh
# TX3 Remote Stream - Screen Capture & H.264 Encoding Service
# Only runs when a remote session is active
# Uses MediaCodec hardware encoder on S905W when available
#
# Version: 1.0.0

CONFIG_DIR="/data/tx3"
LOG_FILE="$CONFIG_DIR/logs/stream.log"
PID_FILE="$CONFIG_DIR/tx3-stream.pid"

# Default profile: S905W / 2GB optimized
CAPTURE_WIDTH=1280
CAPTURE_HEIGHT=720
CAPTURE_FPS=20
BITRATE_KBPS=2000
STREAM_PORT=15100
ENCODER="hw"  # hw | sw
KEYFRAME_INTERVAL=2  # seconds
LOW_LATENCY=1

# Adaptive settings
MIN_FPS=10
MAX_FPS=30
MIN_BITRATE=500
MAX_BITRATE=4000
ADAPTIVE_ENABLED=1
DROP_FRAMES_ON_CONGESTION=1

# State
current_session=""
encoder_pid=0
capture_pid=0
input_pid=0
frame_count=0
dropped_frames=0
started_at=0

log() {
    local level="$1"; shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [STREAM] [$level] $*" >> "$LOG_FILE"
}

# ── Encoder Discovery ──
detect_encoder() {
    # Check for hardware H.264 encoder on S905W
    local codec_list
    codec_list=$(dumpsys media.codec 2>/dev/null || cat /sys/devices/platform/codec_info/encoder 2>/dev/null || echo "")

    if echo "$codec_list" | grep -qi "OMX.amlogic.video.encoder.avc\|c2.amlogic.avc.encoder\|OMX.google.h264.encoder"; then
        log "INFO" "Hardware H.264 encoder detected"
        ENCODER="hw"
        return 0
    fi

    # Check MediaCodec list
    local mc_list
    mc_list=$(cat /proc/media_codecs 2>/dev/null || echo "")
    if echo "$mc_list" | grep -qi "avc\|h264"; then
        log "INFO" "H.264 encoder found in media_codecs"
        ENCODER="hw"
        return 0
    fi

    log "WARN" "No hardware H.264 encoder detected. Using screenrecord fallback."
    ENCODER="screenrecord"
    return 0
}

# ── Profile Selection ──
apply_profile() {
    local profile="${1:-auto}"
    case "$profile" in
        "540p20")
            CAPTURE_WIDTH=960; CAPTURE_HEIGHT=540; CAPTURE_FPS=20; BITRATE_KBPS=1500
            ;;
        "720p20")
            CAPTURE_WIDTH=1280; CAPTURE_HEIGHT=720; CAPTURE_FPS=20; BITRATE_KBPS=2000
            ;;
        "720p25")
            CAPTURE_WIDTH=1280; CAPTURE_HEIGHT=720; CAPTURE_FPS=25; BITRATE_KBPS=2500
            ;;
        "720p30")
            CAPTURE_WIDTH=1280; CAPTURE_HEIGHT=720; CAPTURE_FPS=30; BITRATE_KBPS=3000
            ;;
        "auto"|*)
            # S905W/2GB default
            CAPTURE_WIDTH=1280; CAPTURE_HEIGHT=720; CAPTURE_FPS=20; BITRATE_KBPS=2000
            ;;
    esac
    log "INFO" "Profile: ${CAPTURE_WIDTH}x${CAPTURE_HEIGHT}@${CAPTURE_FPS}fps ${BITRATE_KBPS}kbps encoder=$ENCODER"
}

# ── Screen Capture & Encode Pipeline ──
start_capture() {
    local session_id="$1"
    local profile="${2:-auto}"

    if [ -n "$current_session" ]; then
        log "WARN" "Session already active: $current_session"
        stop_capture
    fi

    current_session="$session_id"
    started_at=$(date +%s)
    frame_count=0
    dropped_frames=0

    detect_encoder
    apply_profile "$profile"

    # Mark stream as active for supervisor
    echo "$session_id" > "$CONFIG_DIR/stream_active"

    log "INFO" "Starting capture for session: $session_id"

    if [ "$ENCODER" = "screenrecord" ]; then
        # Fallback: use Android screenrecord with pipe
        # This pipes raw H.264 to the TCP stream
        screenrecord --output-format=h264 \
            --size "${CAPTURE_WIDTH}x${CAPTURE_HEIGHT}" \
            --bit-rate "$((BITRATE_KBPS * 1000))" \
            --time-limit 0 \
            - 2>/dev/null | \
        while IFS= read -r -n 65536 chunk; do
            # Send to connected client via TCP
            echo -n "$chunk" | nc -q0 localhost $STREAM_PORT 2>/dev/null || true
        done &
        capture_pid=$!
    else
        # Hardware encoder path using native binary
        # tx3-encoder is a native ARM binary that uses MediaCodec API
        if [ -f "$CONFIG_DIR/bin/tx3-encoder" ]; then
            "$CONFIG_DIR/bin/tx3-encoder" \
                --width "$CAPTURE_WIDTH" \
                --height "$CAPTURE_HEIGHT" \
                --fps "$CAPTURE_FPS" \
                --bitrate "$BITRATE_KBPS" \
                --port "$STREAM_PORT" \
                --keyframe-interval "$KEYFRAME_INTERVAL" \
                --low-latency "$LOW_LATENCY" &
            encoder_pid=$!
            log "INFO" "Native encoder started (PID: $encoder_pid)"
        else
            # Fallback to screenrecord
            log "WARN" "Native encoder binary not found, using screenrecord"
            screenrecord --output-format=h264 \
                --size "${CAPTURE_WIDTH}x${CAPTURE_HEIGHT}" \
                --bit-rate "$((BITRATE_KBPS * 1000))" \
                - 2>/dev/null | \
            ncat -l -k -p $STREAM_PORT 2>/dev/null &
            capture_pid=$!
        fi
    fi

    # Start TCP stream server for video output
    start_stream_server &

    # Start input listener
    start_input_listener &
    input_pid=$!

    log "INFO" "Capture pipeline started. Port: $STREAM_PORT"
}

start_stream_server() {
    # Simple TCP server that accepts connections and pipes H.264 data
    # In production this would be a proper binary with framing
    log "INFO" "Stream server listening on port $STREAM_PORT"

    # The actual streaming is handled by the encoder binary or screenrecord pipe
    # This function monitors the stream health
    while [ -f "$CONFIG_DIR/stream_active" ]; do
        sleep 5

        # Check encoder health
        if [ "$encoder_pid" -gt 0 ] && ! kill -0 "$encoder_pid" 2>/dev/null; then
            log "ERROR" "Encoder process died. Session: $current_session"
            # Notify supervisor
            echo "encoder_died" > "$CONFIG_DIR/stream_status"
            break
        fi

        if [ "$capture_pid" -gt 0 ] && ! kill -0 "$capture_pid" 2>/dev/null; then
            log "ERROR" "Capture process died. Session: $current_session"
            echo "capture_died" > "$CONFIG_DIR/stream_status"
            break
        fi

        # Update frame stats
        frame_count=$((frame_count + CAPTURE_FPS * 5))
    done
}

# ── Input Injection ──
start_input_listener() {
    # Listen for input commands on control port
    local control_port=$((STREAM_PORT + 1))  # 15101
    log "INFO" "Input listener on port $control_port"

    while [ -f "$CONFIG_DIR/stream_active" ]; do
        # Read input commands from TCP
        local cmd
        cmd=$(nc -l -p $control_port -w 1 2>/dev/null || true)
        [ -z "$cmd" ] && continue

        local action x y keycode
        action=$(echo "$cmd" | cut -d'|' -f1)
        x=$(echo "$cmd" | cut -d'|' -f2)
        y=$(echo "$cmd" | cut -d'|' -f3)
        keycode=$(echo "$cmd" | cut -d'|' -f4)

        case "$action" in
            "tap")
                input tap "$x" "$y" 2>/dev/null
                ;;
            "swipe")
                local x2 y2 duration
                x2=$(echo "$cmd" | cut -d'|' -f4)
                y2=$(echo "$cmd" | cut -d'|' -f5)
                duration=$(echo "$cmd" | cut -d'|' -f6)
                input swipe "$x" "$y" "$x2" "$y2" "${duration:-300}" 2>/dev/null
                ;;
            "keyevent")
                input keyevent "$keycode" 2>/dev/null
                ;;
            "text")
                local text
                text=$(echo "$cmd" | cut -d'|' -f2-)
                input text "$text" 2>/dev/null
                ;;
            "long_press")
                input swipe "$x" "$y" "$x" "$y" 800 2>/dev/null
                ;;
        esac
    done
}

# ── Stop Capture ──
stop_capture() {
    log "INFO" "Stopping capture for session: $current_session"

    # Kill encoder
    if [ "$encoder_pid" -gt 0 ]; then
        kill "$encoder_pid" 2>/dev/null
        sleep 1
        kill -9 "$encoder_pid" 2>/dev/null
        encoder_pid=0
    fi

    # Kill capture
    if [ "$capture_pid" -gt 0 ]; then
        kill "$capture_pid" 2>/dev/null
        sleep 1
        kill -9 "$capture_pid" 2>/dev/null
        capture_pid=0
    fi

    # Kill input listener
    if [ "$input_pid" -gt 0 ]; then
        kill "$input_pid" 2>/dev/null
        input_pid=0
    fi

    # Release encoder resources
    # MediaCodec release is handled by the native binary on exit
    # For screenrecord, killing the process releases the encoder

    rm -f "$CONFIG_DIR/stream_active"
    rm -f "$CONFIG_DIR/stream_status"

    local duration=0
    if [ "$started_at" -gt 0 ]; then
        duration=$(( $(date +%s) - started_at ))
    fi

    log "INFO" "Session ended: $current_session duration=${duration}s frames=$frame_count dropped=$dropped_frames"
    current_session=""
    started_at=0
}

# ── Adaptive Quality ──
handle_quality_signal() {
    # Called when supervisor sends USR1 (reduce quality)
    if [ "$ADAPTIVE_ENABLED" -eq 1 ]; then
        if [ "$CAPTURE_FPS" -gt "$MIN_FPS" ]; then
            CAPTURE_FPS=$((CAPTURE_FPS - 5))
            [ "$CAPTURE_FPS" -lt "$MIN_FPS" ] && CAPTURE_FPS=$MIN_FPS
            log "INFO" "Adaptive: reduced FPS to $CAPTURE_FPS"
        elif [ "$BITRATE_KBPS" -gt "$MIN_BITRATE" ]; then
            BITRATE_KBPS=$((BITRATE_KBPS - 500))
            [ "$BITRATE_KBPS" -lt "$MIN_BITRATE" ] && BITRATE_KBPS=$MIN_BITRATE
            log "INFO" "Adaptive: reduced bitrate to ${BITRATE_KBPS}kbps"
        else
            log "WARN" "Adaptive: already at minimum quality"
        fi
        # Signal encoder to update parameters (via config file or pipe)
        echo "$CAPTURE_FPS|$BITRATE_KBPS" > "$CONFIG_DIR/stream_params"
    fi
}

trap 'handle_quality_signal' USR1

# ── Command Interface ──
main() {
    echo $$ > "$PID_FILE"
    log "INFO" "TX3 Stream service starting (PID: $$)"

    detect_encoder

    # Listen for session commands via named pipe
    local cmd_pipe="$CONFIG_DIR/stream_cmd"
    rm -f "$cmd_pipe"
    mkfifo "$cmd_pipe" 2>/dev/null

    while true; do
        if [ -p "$cmd_pipe" ]; then
            local line
            read -r line < "$cmd_pipe" 2>/dev/null || { sleep 1; continue; }

            local cmd session_id profile
            cmd=$(echo "$line" | cut -d'|' -f1)
            session_id=$(echo "$line" | cut -d'|' -f2)
            profile=$(echo "$line" | cut -d'|' -f3)

            case "$cmd" in
                "start")
                    start_capture "$session_id" "$profile"
                    ;;
                "stop")
                    stop_capture
                    ;;
                "profile")
                    apply_profile "$profile"
                    ;;
                "status")
                    echo "session=$current_session fps=$CAPTURE_FPS bitrate=$BITRATE_KBPS encoder=$ENCODER frames=$frame_count"
                    ;;
            esac
        else
            sleep 1
        fi
    done
}

cleanup() {
    log "INFO" "Stream service shutting down..."
    stop_capture
    rm -f "$PID_FILE" "$CONFIG_DIR/stream_cmd"
    exit 0
}

trap cleanup INT TERM
main "$@"
