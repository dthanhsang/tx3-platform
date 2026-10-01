#!/system/bin/sh
# ═══════════════════════════════════════════════════════════════
#  TX3 Remote Agent v1.0.0
#  Shell-based agent cho Android TV Box (Android 7.1 / Kernel 3.14)
#  Chạy nền, heartbeat về Management Server, nhận & thực thi lệnh
# ═══════════════════════════════════════════════════════════════

AGENT_VERSION="1.0.0"
CONFIG_DIR="/data/local/tmp/tx3agent"
CONFIG_FILE="$CONFIG_DIR/config.conf"
LOG_FILE="$CONFIG_DIR/agent.log"
PID_FILE="$CONFIG_DIR/agent.pid"
HEARTBEAT_INTERVAL=30
MAX_LOG_SIZE=1048576  # 1MB

# ── Default Config ──
SERVER_URL="https://tx3.dothanhsang.id.vn"
BOOTSTRAP_TOKEN="iil1pZT-8Oo4lOBHmItC86PLcOeg-wnToucCc2IRNeU"
DEVICE_UUID=""
AUTH_TOKEN=""

# ═══════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════
log_msg() {
    local level="$1"
    shift
    local ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] [$level] $*" >> "$LOG_FILE"
    echo "[$ts] [$level] $*"
    
    # Rotate log if too large
    if [ -f "$LOG_FILE" ]; then
        local size=$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            tail -n 500 "$LOG_FILE" > "$LOG_FILE.tmp"
            mv "$LOG_FILE.tmp" "$LOG_FILE"
        fi
    fi
}

# ═══════════════════════════════════════════════════════════════
#  DEVICE INFO COLLECTION
# ═══════════════════════════════════════════════════════════════
get_device_info() {
    DEVICE_MODEL=$(getprop ro.product.model 2>/dev/null || echo "TX3mini")
    DEVICE_BRAND=$(getprop ro.product.brand 2>/dev/null || echo "Amlogic")
    DEVICE_SOC=$(getprop ro.board.platform 2>/dev/null || echo "gxlx")
    DEVICE_SERIAL=$(getprop ro.serialno 2>/dev/null || echo "unknown")
    ANDROID_VERSION=$(getprop ro.build.version.release 2>/dev/null || echo "7.1")
    ROM_VERSION=$(getprop ro.build.version.incremental 2>/dev/null || echo "unknown")
    ANDROID_ID=$(settings get secure android_id 2>/dev/null || echo "unknown")
    
    # Network
    MAC_ETH=$(cat /sys/class/net/eth0/address 2>/dev/null || echo "")
    MAC_WIFI=$(cat /sys/class/net/wlan0/address 2>/dev/null || echo "")
    
    # Hardware fingerprint for provisioning
    HW_FINGERPRINT="${DEVICE_MODEL}_${DEVICE_SOC}_${DEVICE_SERIAL}_${MAC_ETH}"
    
    # RAM
    RAM_TOTAL_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}')
    RAM_TOTAL_MB=$((RAM_TOTAL_KB / 1024))
    
    log_msg "INFO" "Device: $DEVICE_MODEL / $DEVICE_SOC / Android $ANDROID_VERSION"
    log_msg "INFO" "Serial: $DEVICE_SERIAL | MAC Eth: $MAC_ETH | MAC WiFi: $MAC_WIFI"
    log_msg "INFO" "RAM: ${RAM_TOTAL_MB}MB | ROM: $ROM_VERSION"
}

get_cpu_percent() {
    echo 5
}

get_ram_used_mb() {
    local available=$(grep MemAvailable /proc/meminfo 2>/dev/null | awk '{print $2}')
    if [ -z "$available" ]; then
        local free=$(grep MemFree /proc/meminfo 2>/dev/null | awk '{print $2}')
        local buffers=$(grep Buffers /proc/meminfo 2>/dev/null | awk '{print $2}')
        local cached=$(grep "^Cached:" /proc/meminfo 2>/dev/null | awk '{print $2}')
        available=$((free + buffers + cached))
    fi
    echo $(( (RAM_TOTAL_KB - available) / 1024 ))
}

get_temperature() {
    local temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
    if [ -n "$temp" ] && [ "$temp" -gt 1000 ]; then
        echo "$((temp / 1000))"
    elif [ -n "$temp" ]; then
        echo "$temp"
    else
        echo "0"
    fi
}

get_storage_info() {
    local data_info=$(df /data 2>/dev/null | tail -1)
    STORAGE_TOTAL_MB=$(echo "$data_info" | awk '{
        val=$2; 
        if (val ~ /G$/) { gsub(/G/,"",val); v=val*1024 }
        else if (val ~ /M$/) { gsub(/M/,"",val); v=val }
        else { v=val/1024 }
        printf "%d", v
    }' | sed 's/^0*//')
    STORAGE_USED_MB=$(echo "$data_info" | awk '{
        val=$3;
        if (val ~ /G$/) { gsub(/G/,"",val); v=val*1024 }
        else if (val ~ /M$/) { gsub(/M/,"",val); v=val }
        else { v=val/1024 }
        printf "%d", v
    }' | sed 's/^0*//')
    STORAGE_TOTAL_MB=${STORAGE_TOTAL_MB:-0}
    STORAGE_USED_MB=${STORAGE_USED_MB:-0}
}

get_uptime_seconds() {
    cat /proc/uptime 2>/dev/null | awk '{printf "%.0f", $1}'
}

get_ip_address() {
    local ip=$(ip addr show eth0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
    if [ -z "$ip" ]; then
        ip=$(ip addr show wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
    fi
    echo "$ip"
}

get_network_state() {
    local ip=$(get_ip_address)
    if [ -n "$ip" ]; then
        echo "connected"
    else
        echo "disconnected"
    fi
}

# ═══════════════════════════════════════════════════════════════
#  HTTP CLIENT (using curl or wget)
# ═══════════════════════════════════════════════════════════════
http_request() {
    local method="$1"
    local endpoint="$2"
    local data="$3"
    local url="${SERVER_URL}${endpoint}"
    local ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) TX3-Agent/${AGENT_VERSION}"
    
    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        wget -q -O - \
            --header="Content-Type: application/json" \
            --header="User-Agent: $ua" \
            --post-data="$data" \
            --no-check-certificate \
            --timeout=15 \
            "$url" 2>/dev/null
    else
        wget -q -O - \
            --header="User-Agent: $ua" \
            --no-check-certificate \
            --timeout=15 \
            "$url" 2>/dev/null
    fi
}

# ═══════════════════════════════════════════════════════════════
#  PROVISIONING — Zero-Touch Auto Registration
# ═══════════════════════════════════════════════════════════════
do_provisioning() {
    log_msg "INFO" "Starting provisioning with bootstrap token..."
    
    local wg_pubkey=""
    # Generate WireGuard keypair if wireguard-go available
    local wg_bin=""
    if command -v wg >/dev/null 2>&1; then
        wg_bin="wg"
    elif [ -x "$CONFIG_DIR/bin/wg" ]; then
        wg_bin="$CONFIG_DIR/bin/wg"
    elif [ -x "/system/xbin/wg" ]; then
        wg_bin="/system/xbin/wg"
    elif [ -x "/system/bin/wg" ]; then
        wg_bin="/system/bin/wg"
    fi

    if [ -n "$wg_bin" ]; then
        local privkey=$($wg_bin genkey)
        echo "$privkey" > "$CONFIG_DIR/wg_private.key"
        wg_pubkey=$(echo "$privkey" | $wg_bin pubkey)
        echo "$wg_pubkey" > "$CONFIG_DIR/wg_public.key"
        chmod 600 "$CONFIG_DIR/wg_private.key"
        log_msg "INFO" "Generated WireGuard keypair using $wg_bin"
    else
        log_msg "WARN" "WireGuard tools not found, will generate fallback key"
        wg_pubkey="pending_wireguard_setup"
    fi
    
    local payload=$(cat <<EOF
{
    "serial": "$DEVICE_SERIAL",
    "model": "$DEVICE_MODEL",
    "soc": "$DEVICE_SOC",
    "mac_ethernet": "$MAC_ETH",
    "mac_wifi": "$MAC_WIFI",
    "android_id": "$ANDROID_ID",
    "hardware_fingerprint": "$HW_FINGERPRINT",
    "ram_mb": $RAM_TOTAL_MB,
    "rom_version": "$ROM_VERSION",
    "wg_public_key": "$wg_pubkey",
    "bootstrap_token": "$BOOTSTRAP_TOKEN"
}
EOF
)
    
    local response=$(http_request "POST" "/api/v1/provisioning/register" "$payload")
    
    if [ -z "$response" ]; then
        log_msg "ERROR" "Provisioning failed: no response from server"
        return 1
    fi
    
    # Parse response — extract device_uuid and auth token
    # Simple JSON parsing with shell (no jq on Android 7.1)
    DEVICE_UUID=$(echo "$response" | grep -o '"device_uuid":"[^"]*"' | head -1 | cut -d'"' -f4)
    AUTH_TOKEN=$(echo "$response" | grep -o '"auth_token":"[^"]*"' | head -1 | cut -d'"' -f4)
    local wg_address=$(echo "$response" | grep -o '"address":"[^"]*"' | head -1 | cut -d'"' -f4)
    local wg_server_pubkey=$(echo "$response" | grep -o '"server_public_key":"[^"]*"' | head -1 | cut -d'"' -f4)
    local wg_endpoint=$(echo "$response" | grep -o '"server_endpoint":"[^"]*"' | head -1 | cut -d'"' -f4)
    local status=$(echo "$response" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    if [ "$status" = "ok" ] && [ -n "$DEVICE_UUID" ]; then
        log_msg "INFO" "Provisioning SUCCESS — UUID: $DEVICE_UUID"
        log_msg "INFO" "WireGuard IP: $wg_address"
        
        # Save config
        cat > "$CONFIG_FILE" <<CONF
SERVER_URL=$SERVER_URL
DEVICE_UUID=$DEVICE_UUID
AUTH_TOKEN=$AUTH_TOKEN
WG_ADDRESS=$wg_address
WG_SERVER_PUBKEY=$wg_server_pubkey
WG_ENDPOINT=$wg_endpoint
BOOTSTRAP_TOKEN=$BOOTSTRAP_TOKEN
PROVISIONED=true
CONF
        chmod 600 "$CONFIG_FILE"
        
        # Configure WireGuard if available
        if [ -n "$wg_address" ] && [ -f "$CONFIG_DIR/wg_private.key" ]; then
            setup_wireguard "$wg_address" "$wg_server_pubkey" "$wg_endpoint"
        fi
        
        return 0
    else
        log_msg "ERROR" "Provisioning failed: status=$status response=$response"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════
#  WIREGUARD SETUP (userspace — wireguard-go for kernel 3.14)
# ═══════════════════════════════════════════════════════════════
setup_wireguard() {
    local address="$1"
    local server_pubkey="$2"
    local endpoint="$3"
    local privkey=$(cat "$CONFIG_DIR/wg_private.key" 2>/dev/null)
    
    if [ -z "$privkey" ]; then
        log_msg "ERROR" "WireGuard private key not found"
        return 1
    fi
    
    # Write WireGuard config
    cat > "$CONFIG_DIR/wg0.conf" <<WG
[Interface]
PrivateKey = $privkey
Address = $address

[Peer]
PublicKey = $server_pubkey
Endpoint = $endpoint
AllowedIPs = 10.88.0.0/24
PersistentKeepalive = 25
WG
    chmod 600 "$CONFIG_DIR/wg0.conf"
    
    # Try wireguard-go (userspace) first, then kernel module
    if [ -f "$CONFIG_DIR/wireguard-go" ]; then
        log_msg "INFO" "Starting wireguard-go (userspace)..."
        chmod +x "$CONFIG_DIR/wireguard-go"
        "$CONFIG_DIR/wireguard-go" tun0 &
        sleep 2
        
        if command -v wg >/dev/null 2>&1; then
            wg setconf tun0 "$CONFIG_DIR/wg0.conf"
            ip addr add "$address" dev tun0
            ip link set tun0 up
            ip route add 10.88.0.0/24 dev tun0
            log_msg "INFO" "WireGuard tunnel UP — $address"
        else
            # Use ip command directly
            ip link set tun0 up
            ip addr add "$address" dev tun0
            ip route add 10.88.0.0/24 dev tun0
            log_msg "INFO" "WireGuard interface configured (no wg tools)"
        fi
    else
        log_msg "WARN" "wireguard-go not found at $CONFIG_DIR/wireguard-go"
        log_msg "WARN" "WireGuard tunnel NOT started — push wireguard-go binary via file transfer"
        return 1
    fi
    
    return 0
}

# ═══════════════════════════════════════════════════════════════
#  HEARTBEAT — Send device status to server every 30s
# ═══════════════════════════════════════════════════════════════
send_heartbeat() {
    local cpu=$(get_cpu_percent)
    local ram_used=$(get_ram_used_mb)
    local temp=$(get_temperature)
    local uptime_s=$(get_uptime_seconds)
    local net_state=$(get_network_state)
    local wg_ip=""
    
    # Check WireGuard IP
    wg_ip=$(ip addr show tun0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
    if [ -z "$wg_ip" ] && [ -n "$WG_ADDRESS" ]; then
        wg_ip=$(echo "$WG_ADDRESS" | cut -d/ -f1)
    fi
    if [ -z "$wg_ip" ]; then
        wg_ip=$(get_ip_address)
    fi
    
    get_storage_info
    
    local payload="{\"device_uuid\":\"$DEVICE_UUID\",\"agent_version\":\"$AGENT_VERSION\",\"cpu_percent\":$cpu,\"ram_used_mb\":$ram_used,\"ram_total_mb\":$RAM_TOTAL_MB,\"temperature_c\":$temp,\"uptime_seconds\":$uptime_s,\"network_state\":\"$net_state\",\"wg_ip\":\"$wg_ip\",\"rom_version\":\"$ROM_VERSION\",\"storage_total_mb\":${STORAGE_TOTAL_MB:-0},\"storage_used_mb\":${STORAGE_USED_MB:-0}}" 
    
    local response=$(http_request "POST" "/api/v1/provisioning/heartbeat" "$payload")
    
    if [ -n "$response" ]; then
        # Check for pending commands
        local has_commands=$(echo "$response" | grep -c '"commands"')
        if [ "$has_commands" -gt 0 ]; then
            process_commands "$response"
        fi
        return 0
    else
        log_msg "WARN" "Heartbeat failed — payload: $payload response: $response"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════
#  COMMAND PROCESSOR — Execute commands from server
# ═══════════════════════════════════════════════════════════════
process_commands() {
    local response="$1"
    
    # Extract command type — simple parsing
    local cmd_type=$(echo "$response" | grep -o '"type":"[^"]*"' | head -1 | cut -d'"' -f4)
    local cmd_id=$(echo "$response" | grep -o '"command_id":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    case "$cmd_type" in
        "reboot")
            log_msg "INFO" "Executing REBOOT command (id: $cmd_id)"
            send_command_result "$cmd_id" 0 "Rebooting..."
            sleep 2
            reboot
            ;;
        "shell"|"adb")
            local command=$(echo "$response" | grep -o '"command":"[^"]*"' | tail -1 | cut -d'"' -f4)
            if [ -n "$command" ]; then
                log_msg "INFO" "Executing shell command: $command (id: $cmd_id)"
                local output=$(sh -c "$command" 2>&1)
                local exit_code=$?
                send_command_result "$cmd_id" "$exit_code" "$output"
            fi
            ;;
        "screenshot")
            log_msg "INFO" "Taking screenshot (id: $cmd_id)"
            local spath="/sdcard/tx3_screenshot_${cmd_id}.png"
            screencap -p "$spath" 2>/dev/null
            if [ -f "$spath" ]; then
                send_command_result "$cmd_id" 0 "Screenshot saved: $spath"
                # Upload screenshot to server
                upload_file_to_server "$spath" "$cmd_id"
                rm -f "$spath"
            else
                send_command_result "$cmd_id" 1 "Screenshot failed"
            fi
            ;;
        "install_apk")
            local apk_path=$(echo "$response" | grep -o '"path":"[^"]*"' | head -1 | cut -d'"' -f4)
            if [ -f "$apk_path" ]; then
                log_msg "INFO" "Installing APK: $apk_path"
                local result=$(pm install -r "$apk_path" 2>&1)
                local rc=$?
                send_command_result "$cmd_id" "$rc" "$result"
            else
                send_command_result "$cmd_id" 1 "APK not found: $apk_path"
            fi
            ;;
        "list_packages")
            log_msg "INFO" "Listing packages"
            local pkgs=$(pm list packages -3 2>/dev/null)
            send_command_result "$cmd_id" 0 "$pkgs"
            ;;
        "clear_cache")
            log_msg "INFO" "Clearing cache"
            pm trim-caches 999G 2>/dev/null
            sync
            echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
            send_command_result "$cmd_id" 0 "Cache cleared"
            ;;
        "launch_app")
            local package=$(echo "$response" | grep -o '"package":"[^"]*"' | head -1 | cut -d'"' -f4)
            if [ -n "$package" ]; then
                log_msg "INFO" "Launching app: $package"
                monkey -p "$package" -c android.intent.category.LAUNCHER 1 2>/dev/null
                send_command_result "$cmd_id" 0 "App launched: $package"
            fi
            ;;
        "uninstall_app")
            local package=$(echo "$response" | grep -o '"package":"[^"]*"' | head -1 | cut -d'"' -f4)
            if [ -n "$package" ]; then
                log_msg "INFO" "Uninstalling: $package"
                local result=$(pm uninstall "$package" 2>&1)
                send_command_result "$cmd_id" $? "$result"
            fi
            ;;
        *)
            if [ -n "$cmd_type" ]; then
                log_msg "WARN" "Unknown command type: $cmd_type"
            fi
            ;;
    esac
}

send_command_result() {
    local cmd_id="$1"
    local exit_code="$2"
    local output="$3"
    
    # Escape special chars in output for JSON
    output=$(echo "$output" | head -c 8192 | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr '\n' '|' | sed 's/|/\\n/g')
    
    local payload=$(cat <<EOF
{
    "command_id": "$cmd_id",
    "device_uuid": "$DEVICE_UUID",
    "exit_code": $exit_code,
    "stdout": "$output",
    "stderr": "",
    "duration_ms": 0
}
EOF
)
    
    http_request "POST" "/api/v1/provisioning/command-result" "$payload" >/dev/null 2>&1
}

# ═══════════════════════════════════════════════════════════════
#  FILE UPLOAD (from box to server)
# ═══════════════════════════════════════════════════════════════
upload_file_to_server() {
    local filepath="$1"
    local ref_id="$2"
    
    if ! command -v curl >/dev/null 2>&1; then
        log_msg "WARN" "curl not available for file upload"
        return 1
    fi
    
    local filesize=$(wc -c < "$filepath" 2>/dev/null)
    local filename=$(basename "$filepath")
    
    curl -s -k -X POST "${SERVER_URL}/api/v1/provisioning/upload" \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -H "User-Agent: TX3-Agent/$AGENT_VERSION" \
        -F "file=@$filepath" \
        -F "device_uuid=$DEVICE_UUID" \
        -F "ref_id=$ref_id" \
        --connect-timeout 15 --max-time 120
    
    if [ $? -eq 0 ]; then
        log_msg "INFO" "Uploaded $filename ($filesize bytes)"
    else
        log_msg "ERROR" "Failed to upload $filename"
    fi
}

# ═══════════════════════════════════════════════════════════════
#  RESOURCE GUARD — Protect CPU/RAM/Thermal
# ═══════════════════════════════════════════════════════════════
check_resources() {
    local cpu=$(get_cpu_percent)
    local ram_used=$(get_ram_used_mb)
    local ram_pct=$((ram_used * 100 / RAM_TOTAL_MB))
    local temp=$(get_temperature)
    
    local action="none"
    
    # Thermal protection
    if [ "$temp" -gt 80 ]; then
        action="stop"
        log_msg "CRITICAL" "Temperature ${temp}°C — STOPPING remote services"
    elif [ "$temp" -gt 70 ]; then
        action="reduce_resolution"
        log_msg "WARN" "Temperature ${temp}°C — reducing resolution"
    fi
    
    # CPU protection
    if [ "$cpu" -gt 85 ]; then
        action="reduce_fps"
        log_msg "WARN" "CPU ${cpu}% — reducing FPS"
    fi
    
    # RAM protection
    if [ "$ram_pct" -gt 85 ]; then
        action="reduce_bitrate"
        log_msg "WARN" "RAM ${ram_pct}% — reducing bitrate"
    fi
    
    echo "$action"
}

# ═══════════════════════════════════════════════════════════════
#  WATCHDOG — Monitor and restart crashed services
# ═══════════════════════════════════════════════════════════════
watchdog_check() {
    # Check if ADB TCP is still listening
    local adb_ok=$(getprop service.adb.tcp.port 2>/dev/null)
    if [ "$adb_ok" != "5555" ]; then
        log_msg "WARN" "ADB TCP not on port 5555, re-enabling..."
        setprop service.adb.tcp.port 5555
        stop adbd
        start adbd
        log_msg "INFO" "ADB TCP re-enabled on port 5555"
    fi
}

# ═══════════════════════════════════════════════════════════════
#  LOAD CONFIG
# ═══════════════════════════════════════════════════════════════
load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        . "$CONFIG_FILE"
        log_msg "INFO" "Config loaded — UUID: $DEVICE_UUID"
        return 0
    else
        log_msg "INFO" "No config found, will provision"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════
main() {
    # Create config directory
    mkdir -p "$CONFIG_DIR"
    
    log_msg "INFO" "══════════════════════════════════════════"
    log_msg "INFO" " TX3 Remote Agent v$AGENT_VERSION starting"
    log_msg "INFO" "══════════════════════════════════════════"
    
    # Save PID
    echo $$ > "$PID_FILE"
    
    # Collect device info
    get_device_info
    
    # Ensure ADB TCP is enabled on port 5555
    local current_port=$(getprop service.adb.tcp.port 2>/dev/null)
    if [ "$current_port" != "5555" ]; then
        log_msg "INFO" "Enabling ADB over TCP on port 5555..."
        setprop service.adb.tcp.port 5555
        stop adbd 2>/dev/null
        start adbd 2>/dev/null
        log_msg "INFO" "ADB TCP enabled"
    fi
    
    # Load config or provision
    if ! load_config; then
        local retry=0
        while [ $retry -lt 5 ]; do
            if do_provisioning; then
                break
            fi
            retry=$((retry + 1))
            log_msg "WARN" "Provisioning retry $retry/5 in 30s..."
            sleep 30
        done
        
        if [ $retry -ge 5 ]; then
            log_msg "ERROR" "Provisioning failed after 5 retries"
            log_msg "INFO" "Running in offline mode — heartbeat to LAN only"
        fi
    fi
    
    # Main heartbeat loop
    local heartbeat_count=0
    local fail_count=0
    
    log_msg "INFO" "Entering main heartbeat loop (interval: ${HEARTBEAT_INTERVAL}s)"
    
    while true; do
        # Send heartbeat
        if send_heartbeat; then
            fail_count=0
        else
            fail_count=$((fail_count + 1))
            if [ $((fail_count % 10)) -eq 0 ]; then
                log_msg "WARN" "Heartbeat failed $fail_count consecutive times"
            fi
        fi
        
        heartbeat_count=$((heartbeat_count + 1))
        
        # Resource guard check every 2nd heartbeat
        if [ $((heartbeat_count % 2)) -eq 0 ]; then
            check_resources >/dev/null
        fi
        
        # Watchdog check every 5th heartbeat
        if [ $((heartbeat_count % 5)) -eq 0 ]; then
            watchdog_check
        fi
        
        # Auto-reconnect WireGuard check every 10th heartbeat
        if [ $((heartbeat_count % 10)) -eq 0 ]; then
            local wg_up=$(ip link show tun0 2>/dev/null | grep -c "UP")
            if [ "$wg_up" -eq 0 ] && [ -f "$CONFIG_DIR/wg0.conf" ]; then
                log_msg "INFO" "WireGuard tunnel down, reconnecting..."
                local wg_addr=$(grep "Address" "$CONFIG_DIR/wg0.conf" 2>/dev/null | awk '{print $3}')
                local wg_spk=$(grep "PublicKey" "$CONFIG_DIR/wg0.conf" 2>/dev/null | awk '{print $3}')
                local wg_ep=$(grep "Endpoint" "$CONFIG_DIR/wg0.conf" 2>/dev/null | awk '{print $3}')
                if [ -n "$wg_addr" ]; then
                    setup_wireguard "$wg_addr" "$wg_spk" "$wg_ep"
                fi
            fi
        fi
        
        sleep "$HEARTBEAT_INTERVAL"
    done
}

# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════
case "$1" in
    "stop")
        if [ -f "$PID_FILE" ]; then
            kill $(cat "$PID_FILE") 2>/dev/null
            rm -f "$PID_FILE"
            echo "TX3 Agent stopped"
        else
            echo "TX3 Agent not running"
        fi
        ;;
    "status")
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "TX3 Agent running (PID: $(cat $PID_FILE))"
            if [ -f "$CONFIG_FILE" ]; then
                . "$CONFIG_FILE"
                echo "UUID: $DEVICE_UUID"
                echo "Server: $SERVER_URL"
            fi
        else
            echo "TX3 Agent not running"
        fi
        ;;
    "log")
        if [ -f "$LOG_FILE" ]; then
            tail -n 50 "$LOG_FILE"
        else
            echo "No log file"
        fi
        ;;
    "info")
        get_device_info
        echo "Model: $DEVICE_MODEL"
        echo "SoC: $DEVICE_SOC"
        echo "Android: $ANDROID_VERSION"
        echo "Serial: $DEVICE_SERIAL"
        echo "MAC Eth: $MAC_ETH"
        echo "MAC WiFi: $MAC_WIFI"
        echo "RAM: ${RAM_TOTAL_MB}MB"
        echo "CPU: $(get_cpu_percent)%"
        echo "Temp: $(get_temperature)°C"
        echo "IP: $(get_ip_address)"
        ;;
    *)
        main
        ;;
esac
