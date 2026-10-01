#!/system/bin/sh
# TX3 File Transfer Service - Chunked bidirectional file transfer
# Supports: upload, download, browse, resume, hash verification
# Bandwidth throttling and priority management
#
# Version: 1.0.0

CONFIG_DIR="/data/tx3"
LOG_FILE="$CONFIG_DIR/logs/file.log"
PID_FILE="$CONFIG_DIR/tx3-file.pid"
TRANSFER_DIR="$CONFIG_DIR/transfers"

FILE_PORT=15200
CHUNK_SIZE=4194304  # 4MB
MAX_BANDWIDTH_KBPS=0  # 0 = unlimited
REDUCE_WHEN_REMOTE=1
REMOTE_BANDWIDTH_LIMIT_KBPS=2048  # 2Mbps when remote active

log() {
    local level="$1"; shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [FILE] [$level] $*" >> "$LOG_FILE"
}

# ── File Browser ──
list_directory() {
    local path="$1"
    local result=""

    # Sanitize path
    path=$(realpath "$path" 2>/dev/null || echo "$path")

    if [ ! -d "$path" ]; then
        echo '{"error":"Directory not found"}'
        return 1
    fi

    result='{"path":"'"$path"'","entries":['
    local first=1
    for entry in "$path"/*; do
        [ ! -e "$entry" ] && continue
        local name type size modified perms
        name=$(basename "$entry")
        if [ -d "$entry" ]; then
            type="directory"
            size=0
        else
            type="file"
            size=$(stat -c%s "$entry" 2>/dev/null || echo 0)
        fi
        modified=$(stat -c%Y "$entry" 2>/dev/null || echo 0)
        modified=$((modified * 1000))
        perms=$(stat -c%A "$entry" 2>/dev/null || echo "----------")

        [ $first -eq 0 ] && result="$result,"
        result="$result{\"name\":\"$name\",\"type\":\"$type\",\"size\":$size,\"modified\":$modified,\"permissions\":\"$perms\"}"
        first=0
    done
    result="$result]}"
    echo "$result"
}

# ── Chunked Upload (PC -> Box) ──
receive_file() {
    local transfer_id="$1"
    local destination="$2"
    local expected_size="$3"
    local expected_hash="$4"
    local resume_offset="${5:-0}"

    mkdir -p "$TRANSFER_DIR"
    local meta_file="$TRANSFER_DIR/${transfer_id}.meta"
    local temp_file="$TRANSFER_DIR/${transfer_id}.tmp"

    log "INFO" "Upload start: id=$transfer_id dest=$destination size=$expected_size resume=$resume_offset"

    # Save transfer metadata
    cat > "$meta_file" << EOF
transfer_id=$transfer_id
destination=$destination
expected_size=$expected_size
expected_hash=$expected_hash
status=active
started_at=$(date +%s)
received=0
EOF

    # Prepare destination directory
    local dest_dir
    dest_dir=$(dirname "$destination")
    mkdir -p "$dest_dir" 2>/dev/null

    local received=$resume_offset
    local chunk_port=$((FILE_PORT + 1))

    # Open file for writing
    if [ "$resume_offset" -gt 0 ] && [ -f "$temp_file" ]; then
        log "INFO" "Resuming upload from offset $resume_offset"
    else
        : > "$temp_file"
        received=0
    fi

    # Receive chunks
    while [ "$received" -lt "$expected_size" ]; do
        local remaining=$((expected_size - received))
        local this_chunk=$CHUNK_SIZE
        [ "$remaining" -lt "$this_chunk" ] && this_chunk=$remaining

        # Check bandwidth throttling
        if [ "$REDUCE_WHEN_REMOTE" -eq 1 ] && [ -f "$CONFIG_DIR/stream_active" ]; then
            # Remote session active - throttle
            if [ "$MAX_BANDWIDTH_KBPS" -eq 0 ] || [ "$MAX_BANDWIDTH_KBPS" -gt "$REMOTE_BANDWIDTH_LIMIT_KBPS" ]; then
                # Add small delay between chunks to throttle
                sleep 0.1
            fi
        fi

        # Check disk space
        local avail
        avail=$(df /data 2>/dev/null | awk 'NR==2{print $4}')
        avail=$((avail * 1024))  # KB to bytes
        if [ "$avail" -lt "$((this_chunk * 2))" ]; then
            log "ERROR" "Insufficient disk space for transfer $transfer_id"
            sed -i 's/status=active/status=failed/' "$meta_file"
            echo '{"transfer_id":"'"$transfer_id"'","status":"error","error":"insufficient_disk_space","offset":'"$received"'}'
            return 1
        fi

        # Receive chunk via TCP
        dd bs="$this_chunk" count=1 iflag=fullblock 2>/dev/null | \
            dd bs="$this_chunk" seek=$((received / this_chunk)) of="$temp_file" conv=notrunc 2>/dev/null

        received=$((received + this_chunk))
        sed -i "s/received=.*/received=$received/" "$meta_file" 2>/dev/null

        # Calculate speed
        local elapsed=$(($(date +%s) - $(grep started_at "$meta_file" | cut -d= -f2)))
        local speed=0
        [ "$elapsed" -gt 0 ] && speed=$((received / elapsed))

        # Ack chunk
        echo '{"transfer_id":"'"$transfer_id"'","offset":'"$received"',"status":"ok","speed_bps":'"$speed"'}'
    done

    # Verify hash
    if [ -n "$expected_hash" ]; then
        local actual_hash
        actual_hash=$(sha256sum "$temp_file" 2>/dev/null | cut -d' ' -f1)
        if [ "$actual_hash" != "$expected_hash" ]; then
            log "ERROR" "Hash mismatch for transfer $transfer_id: expected=$expected_hash actual=$actual_hash"
            sed -i 's/status=active/status=hash_mismatch/' "$meta_file"
            echo '{"transfer_id":"'"$transfer_id"'","status":"hash_mismatch","expected":"'"$expected_hash"'","actual":"'"$actual_hash"'"}'
            return 1
        fi
    fi

    # Move to final destination
    mv "$temp_file" "$destination"
    chmod 644 "$destination" 2>/dev/null
    sed -i 's/status=active/status=completed/' "$meta_file"

    log "INFO" "Upload complete: $transfer_id -> $destination ($expected_size bytes)"
    echo '{"transfer_id":"'"$transfer_id"'","status":"ok","total_bytes":'"$expected_size"',"hash_sha256":"'"$expected_hash"'"}'
}

# ── Chunked Download (Box -> PC) ──
send_file() {
    local transfer_id="$1"
    local source_path="$2"
    local resume_offset="${3:-0}"

    if [ ! -f "$source_path" ]; then
        log "ERROR" "File not found: $source_path"
        echo '{"transfer_id":"'"$transfer_id"'","status":"error","error":"file_not_found"}'
        return 1
    fi

    local file_size
    file_size=$(stat -c%s "$source_path")
    local file_hash
    file_hash=$(sha256sum "$source_path" 2>/dev/null | cut -d' ' -f1)

    log "INFO" "Download start: id=$transfer_id source=$source_path size=$file_size resume=$resume_offset"

    echo '{"transfer_id":"'"$transfer_id"'","file_size":'"$file_size"',"hash_sha256":"'"$file_hash"'"}'

    local sent=$resume_offset

    while [ "$sent" -lt "$file_size" ]; do
        local remaining=$((file_size - sent))
        local this_chunk=$CHUNK_SIZE
        [ "$remaining" -lt "$this_chunk" ] && this_chunk=$remaining

        # Throttle if remote active
        if [ "$REDUCE_WHEN_REMOTE" -eq 1 ] && [ -f "$CONFIG_DIR/stream_active" ]; then
            sleep 0.05
        fi

        dd if="$source_path" bs="$this_chunk" skip=$((sent / CHUNK_SIZE)) count=1 2>/dev/null
        sent=$((sent + this_chunk))
    done

    log "INFO" "Download complete: $transfer_id ($file_size bytes)"
}

# ── File Operations ──
create_directory() {
    local path="$1"
    if mkdir -p "$path" 2>/dev/null; then
        log "INFO" "Directory created: $path"
        echo '{"status":"ok","path":"'"$path"'"}'
    else
        log "ERROR" "Failed to create directory: $path"
        echo '{"status":"error","error":"permission_denied"}'
    fi
}

rename_file() {
    local old_path="$1"
    local new_path="$2"
    if mv "$old_path" "$new_path" 2>/dev/null; then
        log "INFO" "Renamed: $old_path -> $new_path"
        echo '{"status":"ok"}'
    else
        log "ERROR" "Failed to rename: $old_path"
        echo '{"status":"error","error":"rename_failed"}'
    fi
}

delete_file() {
    local path="$1"
    if rm -rf "$path" 2>/dev/null; then
        log "INFO" "Deleted: $path"
        echo '{"status":"ok"}'
    else
        log "ERROR" "Failed to delete: $path"
        echo '{"status":"error","error":"delete_failed"}'
    fi
}

# ── APK Installation ──
install_apk() {
    local apk_path="$1"
    local command_id="$2"

    if [ ! -f "$apk_path" ]; then
        echo '{"command_id":"'"$command_id"'","status":"error","error":"apk_not_found"}'
        return 1
    fi

    log "INFO" "Installing APK: $apk_path"
    local output
    output=$(pm install -r "$apk_path" 2>&1)
    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        log "INFO" "APK installed successfully: $apk_path"
        echo '{"command_id":"'"$command_id"'","status":"ok","output":"'"$output"'"}'
    else
        log "ERROR" "APK install failed: $output"
        echo '{"command_id":"'"$command_id"'","status":"error","output":"'"$output"'"}'
    fi
}

# ── Command Processor ──
process_command() {
    local cmd_json="$1"
    local cmd_type
    cmd_type=$(echo "$cmd_json" | sed -n 's/.*"type":"\([^"]*\)".*/\1/p')

    case "$cmd_type" in
        "file_list")
            local path
            path=$(echo "$cmd_json" | sed -n 's/.*"path":"\([^"]*\)".*/\1/p')
            list_directory "$path"
            ;;
        "file_upload_start")
            local tid dest fsize hash offset
            tid=$(echo "$cmd_json" | sed -n 's/.*"transfer_id":"\([^"]*\)".*/\1/p')
            dest=$(echo "$cmd_json" | sed -n 's/.*"destination":"\([^"]*\)".*/\1/p')
            fsize=$(echo "$cmd_json" | sed -n 's/.*"file_size":\([0-9]*\).*/\1/p')
            hash=$(echo "$cmd_json" | sed -n 's/.*"hash_sha256":"\([^"]*\)".*/\1/p')
            offset=$(echo "$cmd_json" | sed -n 's/.*"resume_offset":\([0-9]*\).*/\1/p')
            receive_file "$tid" "$dest" "$fsize" "$hash" "${offset:-0}"
            ;;
        "file_download_start")
            local tid path offset
            tid=$(echo "$cmd_json" | sed -n 's/.*"transfer_id":"\([^"]*\)".*/\1/p')
            path=$(echo "$cmd_json" | sed -n 's/.*"path":"\([^"]*\)".*/\1/p')
            offset=$(echo "$cmd_json" | sed -n 's/.*"resume_offset":\([0-9]*\).*/\1/p')
            send_file "$tid" "$path" "${offset:-0}"
            ;;
        "file_mkdir")
            local path
            path=$(echo "$cmd_json" | sed -n 's/.*"path":"\([^"]*\)".*/\1/p')
            create_directory "$path"
            ;;
        "file_rename")
            local old new
            old=$(echo "$cmd_json" | sed -n 's/.*"old_path":"\([^"]*\)".*/\1/p')
            new=$(echo "$cmd_json" | sed -n 's/.*"new_path":"\([^"]*\)".*/\1/p')
            rename_file "$old" "$new"
            ;;
        "file_delete")
            local path
            path=$(echo "$cmd_json" | sed -n 's/.*"path":"\([^"]*\)".*/\1/p')
            delete_file "$path"
            ;;
        "apk_install")
            local apk cid
            apk=$(echo "$cmd_json" | sed -n 's/.*"apk_path":"\([^"]*\)".*/\1/p')
            cid=$(echo "$cmd_json" | sed -n 's/.*"command_id":"\([^"]*\)".*/\1/p')
            install_apk "$apk" "$cid"
            ;;
    esac
}

# ── Main Service Loop ──
main() {
    mkdir -p "$TRANSFER_DIR"
    echo $$ > "$PID_FILE"
    log "INFO" "TX3 File Transfer service starting (PID: $$)"

    # Mark file service as active
    touch "$CONFIG_DIR/file_active"

    # Listen for commands via named pipe
    local cmd_pipe="$CONFIG_DIR/file_cmd"
    rm -f "$cmd_pipe"
    mkfifo "$cmd_pipe" 2>/dev/null

    while true; do
        if [ -p "$cmd_pipe" ]; then
            local line
            read -r line < "$cmd_pipe" 2>/dev/null || { sleep 1; continue; }
            [ -n "$line" ] && process_command "$line"
        else
            sleep 1
        fi
    done
}

cleanup() {
    log "INFO" "File Transfer service shutting down..."
    rm -f "$PID_FILE" "$CONFIG_DIR/file_active" "$CONFIG_DIR/file_cmd"
    exit 0
}

trap cleanup INT TERM
main "$@"
