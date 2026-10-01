#!/system/bin/sh
# TX3 Remote Supervisor - Process Monitor & Resource Guard
# Monitors tx3-stream, tx3-file processes
# Handles restart, resource limits, thermal throttling
#
# Version: 1.0.0

CONFIG_DIR="/data/tx3"
LOG_FILE="$CONFIG_DIR/logs/supervisor.log"
PID_FILE="$CONFIG_DIR/tx3-supervisor.pid"

# Resource thresholds (will be calibrated on real hardware)
SOFT_RAM_PERCENT=80
HARD_RAM_PERCENT=90
SOFT_CPU_PERCENT=85
HARD_CPU_PERCENT=95
SOFT_TEMP_C=75
HARD_TEMP_C=85
MAX_STREAM_RESTARTS=5
STREAM_RESTART_WINDOW=300  # seconds
CHECK_INTERVAL=5

# Process tracking
stream_pid=0
file_pid=0
stream_restart_count=0
stream_restart_window_start=0

log() {
    local level="$1"; shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUPERVISOR] [$level] $*" >> "$LOG_FILE"
}

get_ram_percent() {
    free 2>/dev/null | awk '/^Mem:/{printf "%.0f", $3/$2*100}' || echo "0"
}

get_cpu_percent() {
    top -bn1 2>/dev/null | head -5 | awk '/CPU:/{gsub(/%/,""); printf "%.0f", 100-$8}' || echo "0"
}

get_temperature() {
    local temp
    temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "0")
    echo $((temp / 1000))
}

get_disk_percent() {
    df /data 2>/dev/null | awk 'NR==2{gsub(/%/,""); print $5}' || echo "0"
}

is_process_alive() {
    [ -n "$1" ] && [ "$1" -gt 0 ] && kill -0 "$1" 2>/dev/null
}

# ── Stream Process Management ──
start_stream() {
    if is_process_alive "$stream_pid"; then
        return 0
    fi
    log "INFO" "Starting tx3-stream..."
    /system/bin/tx3-stream &
    stream_pid=$!
    log "INFO" "tx3-stream started (PID: $stream_pid)"
}

stop_stream() {
    if is_process_alive "$stream_pid"; then
        log "INFO" "Stopping tx3-stream (PID: $stream_pid)..."
        kill "$stream_pid" 2>/dev/null
        sleep 2
        if is_process_alive "$stream_pid"; then
            kill -9 "$stream_pid" 2>/dev/null
        fi
        stream_pid=0
        log "INFO" "tx3-stream stopped"
    fi
}

restart_stream() {
    local now
    now=$(date +%s)

    # Check restart rate limiting
    if [ $((now - stream_restart_window_start)) -gt $STREAM_RESTART_WINDOW ]; then
        stream_restart_count=0
        stream_restart_window_start=$now
    fi

    stream_restart_count=$((stream_restart_count + 1))
    if [ $stream_restart_count -gt $MAX_STREAM_RESTARTS ]; then
        log "ERROR" "tx3-stream exceeded max restarts ($MAX_STREAM_RESTARTS in ${STREAM_RESTART_WINDOW}s). Not restarting."
        return 1
    fi

    log "WARN" "Restarting tx3-stream (restart #$stream_restart_count)"
    stop_stream
    sleep 1
    start_stream
}

# ── File Transfer Process Management ──
start_file_service() {
    if is_process_alive "$file_pid"; then
        return 0
    fi
    log "INFO" "Starting tx3-file..."
    /system/bin/tx3-file &
    file_pid=$!
    log "INFO" "tx3-file started (PID: $file_pid)"
}

stop_file_service() {
    if is_process_alive "$file_pid"; then
        log "INFO" "Stopping tx3-file (PID: $file_pid)..."
        kill "$file_pid" 2>/dev/null
        sleep 2
        if is_process_alive "$file_pid"; then
            kill -9 "$file_pid" 2>/dev/null
        fi
        file_pid=0
        log "INFO" "tx3-file stopped"
    fi
}

# ── Resource Guard ──
check_resources() {
    local ram_pct cpu_pct temp_c disk_pct
    ram_pct=$(get_ram_percent)
    cpu_pct=$(get_cpu_percent)
    temp_c=$(get_temperature)
    disk_pct=$(get_disk_percent)

    local action="none"

    # Hard limits - stop services
    if [ "$ram_pct" -ge "$HARD_RAM_PERCENT" ]; then
        log "ERROR" "HARD RAM limit ($ram_pct% >= $HARD_RAM_PERCENT%). Stopping remote services."
        stop_stream
        stop_file_service
        action="hard_stop"
    elif [ "$temp_c" -ge "$HARD_TEMP_C" ]; then
        log "ERROR" "HARD TEMP limit (${temp_c}°C >= ${HARD_TEMP_C}°C). Stopping remote services."
        stop_stream
        stop_file_service
        action="hard_stop"
    elif [ "$cpu_pct" -ge "$HARD_CPU_PERCENT" ]; then
        log "ERROR" "HARD CPU limit ($cpu_pct% >= $HARD_CPU_PERCENT%). Stopping stream."
        stop_stream
        action="hard_stop"
    fi

    # Soft limits - signal to reduce quality
    if [ "$action" = "none" ]; then
        if [ "$ram_pct" -ge "$SOFT_RAM_PERCENT" ]; then
            log "WARN" "Soft RAM limit ($ram_pct%). Signaling quality reduction."
            action="reduce"
        elif [ "$temp_c" -ge "$SOFT_TEMP_C" ]; then
            log "WARN" "Soft TEMP limit (${temp_c}°C). Signaling quality reduction."
            action="reduce"
        elif [ "$cpu_pct" -ge "$SOFT_CPU_PERCENT" ]; then
            log "WARN" "Soft CPU limit ($cpu_pct%). Signaling quality reduction."
            action="reduce"
        fi
    fi

    # Signal resource state to stream process
    if [ "$action" = "reduce" ] && is_process_alive "$stream_pid"; then
        kill -USR1 "$stream_pid" 2>/dev/null  # Signal to reduce quality
    fi

    # Disk space check for file transfers
    if [ "$disk_pct" -ge 95 ]; then
        log "ERROR" "Disk nearly full ($disk_pct%). Stopping file transfers."
        stop_file_service
    fi

    echo "$action"
}

# ── Process Health Monitor ──
check_process_health() {
    # Check if stream process is expected to be running
    if [ -f "$CONFIG_DIR/stream_active" ]; then
        if ! is_process_alive "$stream_pid"; then
            log "WARN" "tx3-stream died unexpectedly"
            restart_stream
        fi

        # Check memory leak: if stream uses more than 150MB, restart it
        if is_process_alive "$stream_pid"; then
            local stream_rss
            stream_rss=$(awk '/VmRSS/{print $2}' /proc/$stream_pid/status 2>/dev/null || echo "0")
            stream_rss=$((stream_rss / 1024))  # KB to MB
            if [ "$stream_rss" -gt 150 ]; then
                log "WARN" "tx3-stream using ${stream_rss}MB RAM. Possible memory leak. Restarting."
                restart_stream
            fi
        fi
    fi

    # Check file service
    if [ -f "$CONFIG_DIR/file_active" ]; then
        if ! is_process_alive "$file_pid"; then
            log "WARN" "tx3-file died unexpectedly. Restarting."
            start_file_service
        fi
    fi
}

# ── Main Loop ──
main() {
    echo $$ > "$PID_FILE"
    log "INFO" "TX3 Supervisor starting (PID: $$)"

    # Start file service (always available)
    start_file_service

    while true; do
        check_resources
        check_process_health
        sleep $CHECK_INTERVAL
    done
}

cleanup() {
    log "INFO" "Supervisor shutting down..."
    stop_stream
    stop_file_service
    rm -f "$PID_FILE"
    exit 0
}

trap cleanup INT TERM
main "$@"
