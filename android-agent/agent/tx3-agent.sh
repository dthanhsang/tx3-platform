#!/system/bin/sh
# TX3 Remote Agent - Main Agent Daemon
# Runs as root/system on Android TV Box
# Handles: device identity, heartbeat, command reception, session management
#
# Version: 1.0.0

AGENT_VERSION="1.0.0"
PROTOCOL_VERSION=1
CONFIG_DIR="/data/tx3"
CONFIG_FILE="$CONFIG_DIR/agent.conf"
IDENTITY_FILE="$CONFIG_DIR/device_identity.json"
LOG_DIR="$CONFIG_DIR/logs"
LOG_FILE="$LOG_DIR/agent.log"
PID_FILE="$CONFIG_DIR/tx3-agent.pid"
WG_CONFIG="$CONFIG_DIR/wg0.conf"

HEARTBEAT_INTERVAL=30
MAX_LOG_SIZE=5242880  # 5MB
MAX_LOG_FILES=3
PROVISION_RETRY_INTERVAL=30
PROVISION_MAX_RETRIES=0  # 0 = infinite

# ── Logging ──
log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" >> "$LOG_FILE"
    # Also logcat
    log -t TX3Agent -p "${level:0:1}" "$msg" 2>/dev/null || true
}

rotate_logs() {
    if [ -f "$LOG_FILE" ]; then
        local size
        size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            local i=$MAX_LOG_FILES
            while [ "$i" -gt 1 ]; do
                local prev=$((i - 1))
                [ -f "${LOG_FILE}.$prev" ] && mv "${LOG_FILE}.$prev" "${LOG_FILE}.$i"
                i=$prev
            done
            mv "$LOG_FILE" "${LOG_FILE}.1"
            touch "$LOG_FILE"
            log "INFO" "Log rotated"
        fi
    fi
}

# ── Device Identity ──
collect_identity() {
    local mac_wifi mac_eth serial android_id model soc ram_mb
    mac_wifi=$(cat /sys/class/net/wlan0/address 2>/dev/null || echo "")
    mac_eth=$(cat /sys/class/net/eth0/address 2>/dev/null || echo "")
    serial=$(getprop ro.serialno 2>/dev/null || echo "")
    android_id=$(settings get secure android_id 2>/dev/null || echo "")
    model=$(getprop ro.product.model 2>/dev/null || echo "")
    soc=$(getprop ro.board.platform 2>/dev/null || echo "")
    ram_mb=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")
    local rom_version
    rom_version=$(getprop ro.build.display.id 2>/dev/null || echo "unknown")

    # Hardware fingerprint: hash of stable identifiers
    local fp_input="${mac_wifi}|${mac_eth}|${serial}|${soc}|${model}"
    local hw_fingerprint
    hw_fingerprint=$(echo -n "$fp_input" | md5sum | cut -d' ' -f1)

    cat > "$IDENTITY_FILE" << EOF
{
    "mac_wifi": "$mac_wifi",
    "mac_ethernet": "$mac_eth",
    "serial": "$serial",
    "android_id": "$android_id",
    "model": "$model",
    "soc": "$soc",
    "ram_mb": $ram_mb,
    "rom_version": "$rom_version",
    "hardware_fingerprint": "$hw_fingerprint",
    "agent_version": "$AGENT_VERSION",
    "protocol_version": $PROTOCOL_VERSION
}
EOF
    log "INFO" "Device identity collected: model=$model soc=$soc ram=${ram_mb}MB"
}

# ── Network Check ──
wait_for_network() {
    log "INFO" "Waiting for network..."
    local attempts=0
    while true; do
        if ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
            log "INFO" "Network available"
            return 0
        fi
        attempts=$((attempts + 1))
        if [ $((attempts % 10)) -eq 0 ]; then
            log "INFO" "Still waiting for network (attempt $attempts)"
        fi
        sleep 5
    done
}

# ── Provisioning ──
provision() {
    if [ -f "$CONFIG_FILE" ] && grep -q "device_uuid" "$CONFIG_FILE" 2>/dev/null; then
        log "INFO" "Device already provisioned"
        return 0
    fi

    log "INFO" "Starting provisioning..."

    # Read bootstrap config
    local server_url bootstrap_token
    server_url=$(grep "^PROVISION_SERVER=" "$CONFIG_DIR/bootstrap.conf" 2>/dev/null | cut -d= -f2-)
    bootstrap_token=$(grep "^BOOTSTRAP_TOKEN=" "$CONFIG_DIR/bootstrap.conf" 2>/dev/null | cut -d= -f2-)

    if [ -z "$server_url" ] || [ -z "$bootstrap_token" ]; then
        log "ERROR" "Missing bootstrap configuration"
        return 1
    fi

    # Generate WireGuard keypair
    local wg_private wg_public
    if command -v wg >/dev/null 2>&1; then
        wg_private=$(wg genkey)
        wg_public=$(echo "$wg_private" | wg pubkey)
    else
        # Fallback: use bundled wg binary
        wg_private=$("$CONFIG_DIR/bin/wg" genkey)
        wg_public=$(echo "$wg_private" | "$CONFIG_DIR/bin/wg" pubkey)
    fi

    # Store private key securely
    echo "$wg_private" > "$CONFIG_DIR/wg_private.key"
    chmod 600 "$CONFIG_DIR/wg_private.key"

    # Read identity
    local identity
    identity=$(cat "$IDENTITY_FILE")

    # Build provision request
    local request
    request=$(cat << EOF
{
    "bootstrap_token": "$bootstrap_token",
    "wg_public_key": "$wg_public",
    $(echo "$identity" | sed '1d;$d')
}
EOF
)

    local retries=0
    while true; do
        log "INFO" "Provisioning attempt $((retries + 1))..."
        local response
        response=$(curl -s -X POST \
            -H "Content-Type: application/json" \
            -d "$request" \
            --connect-timeout 10 \
            --max-time 30 \
            "${server_url}/api/v1/provisioning/provision" 2>/dev/null)

        if [ $? -eq 0 ] && echo "$response" | grep -q '"status":"ok"'; then
            log "INFO" "Provisioning successful"

            # Extract config
            local device_uuid wg_address wg_server_pubkey wg_endpoint wg_allowed_ips
            local heartbeat_int api_url ws_url
            device_uuid=$(echo "$response" | sed -n 's/.*"device_uuid":"\([^"]*\)".*/\1/p')
            wg_address=$(echo "$response" | sed -n 's/.*"address":"\([^"]*\)".*/\1/p')
            wg_server_pubkey=$(echo "$response" | sed -n 's/.*"server_public_key":"\([^"]*\)".*/\1/p')
            wg_endpoint=$(echo "$response" | sed -n 's/.*"server_endpoint":"\([^"]*\)".*/\1/p')
            wg_allowed_ips=$(echo "$response" | sed -n 's/.*"allowed_ips":"\([^"]*\)".*/\1/p')
            heartbeat_int=$(echo "$response" | sed -n 's/.*"heartbeat_interval":\([0-9]*\).*/\1/p')
            api_url=$(echo "$response" | sed -n 's/.*"server_api_url":"\([^"]*\)".*/\1/p')
            ws_url=$(echo "$response" | sed -n 's/.*"server_ws_url":"\([^"]*\)".*/\1/p')

            # Save agent config
            cat > "$CONFIG_FILE" << EOFCFG
device_uuid=$device_uuid
server_api_url=$api_url
server_ws_url=$ws_url
heartbeat_interval=${heartbeat_int:-30}
wg_address=$wg_address
EOFCFG

            # Generate WireGuard config
            cat > "$WG_CONFIG" << EOFWG
[Interface]
PrivateKey = $wg_private
Address = $wg_address

[Peer]
PublicKey = $wg_server_pubkey
Endpoint = $wg_endpoint
AllowedIPs = ${wg_allowed_ips:-10.88.0.0/24}
PersistentKeepalive = 25
EOFWG
            chmod 600 "$WG_CONFIG"
            log "INFO" "Device UUID: $device_uuid, WG IP: $wg_address"
            return 0
        else
            local error_msg
            error_msg=$(echo "$response" | sed -n 's/.*"error":"\([^"]*\)".*/\1/p')
            log "WARN" "Provisioning failed: ${error_msg:-no response}"
        fi

        retries=$((retries + 1))
        if [ "$PROVISION_MAX_RETRIES" -gt 0 ] && [ "$retries" -ge "$PROVISION_MAX_RETRIES" ]; then
            log "ERROR" "Provisioning failed after $retries attempts"
            return 1
        fi

        sleep $PROVISION_RETRY_INTERVAL
    done
}

# ── WireGuard ──
start_wireguard() {
    if [ ! -f "$WG_CONFIG" ]; then
        log "ERROR" "WireGuard config not found"
        return 1
    fi

    log "INFO" "Starting WireGuard..."

    # Check if wg module is loaded
    if ! lsmod 2>/dev/null | grep -q wireguard; then
        insmod /system/lib/modules/wireguard.ko 2>/dev/null || true
    fi

    # Use ip link / wg-quick style setup
    local wg_bin
    if command -v wg >/dev/null 2>&1; then
        wg_bin="wg"
    else
        wg_bin="$CONFIG_DIR/bin/wg"
    fi

    # Extract config values
    local private_key address peer_pubkey endpoint allowed_ips keepalive
    private_key=$(grep "PrivateKey" "$WG_CONFIG" | cut -d= -f2- | tr -d ' ')
    address=$(grep "Address" "$WG_CONFIG" | cut -d= -f2- | tr -d ' ')
    peer_pubkey=$(grep "PublicKey" "$WG_CONFIG" | cut -d= -f2- | tr -d ' ')
    endpoint=$(grep "Endpoint" "$WG_CONFIG" | cut -d= -f2- | tr -d ' ')
    allowed_ips=$(grep "AllowedIPs" "$WG_CONFIG" | cut -d= -f2- | tr -d ' ')
    keepalive=$(grep "PersistentKeepalive" "$WG_CONFIG" | cut -d= -f2- | tr -d ' ')

    # Bring up interface
    ip link del wg0 2>/dev/null || true
    ip link add wg0 type wireguard
    "$wg_bin" set wg0 private-key "$CONFIG_DIR/wg_private.key"
    "$wg_bin" set wg0 peer "$peer_pubkey" endpoint "$endpoint" allowed-ips "$allowed_ips" persistent-keepalive "${keepalive:-25}"
    ip addr add "$address" dev wg0
    ip link set wg0 up
    ip route add "$allowed_ips" dev wg0 2>/dev/null || true

    log "INFO" "WireGuard interface wg0 up: $address"
    return 0
}

check_wireguard() {
    if ip link show wg0 > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

restart_wireguard() {
    log "WARN" "Restarting WireGuard..."
    ip link del wg0 2>/dev/null || true
    sleep 2
    start_wireguard
}

# ── Telemetry Collection ──
collect_telemetry() {
    local cpu_percent ram_used ram_total temp storage_used storage_total
    cpu_percent=$(top -bn1 2>/dev/null | head -5 | awk '/CPU:/{gsub(/%/,""); print 100-$8}' || echo "0")
    ram_used=$(free -m 2>/dev/null | awk '/^Mem:/{print $3}' || echo "0")
    ram_total=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")
    temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "0")
    temp=$((temp / 1000))  # millidegrees to degrees
    storage_used=$(df /data 2>/dev/null | awk 'NR==2{print int($3/1024)}' || echo "0")
    storage_total=$(df /data 2>/dev/null | awk 'NR==2{print int($2/1024)}' || echo "0")

    echo "{\"cpu_percent\":$cpu_percent,\"ram_used_mb\":$ram_used,\"ram_total_mb\":$ram_total,\"temperature_c\":$temp,\"storage_used_mb\":$storage_used,\"storage_total_mb\":$storage_total}"
}

# ── Heartbeat ──
send_heartbeat() {
    local device_uuid server_url
    device_uuid=$(grep "^device_uuid=" "$CONFIG_FILE" | cut -d= -f2-)
    server_url=$(grep "^server_api_url=" "$CONFIG_FILE" | cut -d= -f2-)

    if [ -z "$device_uuid" ] || [ -z "$server_url" ]; then
        return 1
    fi

    local uptime_seconds
    uptime_seconds=$(cat /proc/uptime 2>/dev/null | cut -d. -f1)
    local wg_ip
    wg_ip=$(ip addr show wg0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
    local rom_version
    rom_version=$(getprop ro.build.display.id 2>/dev/null)
    local network_state="connected"
    if ! ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1; then
        network_state="disconnected"
    fi

    local telemetry
    telemetry=$(collect_telemetry)
    local cpu ram_used ram_total temp storage_used storage_total
    cpu=$(echo "$telemetry" | sed -n 's/.*"cpu_percent":\([^,]*\).*/\1/p')
    ram_used=$(echo "$telemetry" | sed -n 's/.*"ram_used_mb":\([^,]*\).*/\1/p')
    ram_total=$(echo "$telemetry" | sed -n 's/.*"ram_total_mb":\([^,]*\).*/\1/p')
    temp=$(echo "$telemetry" | sed -n 's/.*"temperature_c":\([^,]*\).*/\1/p')
    storage_used=$(echo "$telemetry" | sed -n 's/.*"storage_used_mb":\([^,]*\).*/\1/p')
    storage_total=$(echo "$telemetry" | sed -n 's/.*"storage_total_mb":\([^}]*\).*/\1/p')

    local payload
    payload="{\"device_uuid\":\"$device_uuid\",\"agent_version\":\"$AGENT_VERSION\",\"rom_version\":\"$rom_version\",\"uptime_seconds\":$uptime_seconds,\"wg_ip\":\"$wg_ip\",\"network_state\":\"$network_state\",\"ram_used_mb\":$ram_used,\"ram_total_mb\":$ram_total,\"cpu_percent\":$cpu,\"temperature_c\":$temp,\"storage_used_mb\":$storage_used,\"storage_total_mb\":$storage_total}"

    local response
    response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "$payload" \
        --connect-timeout 5 \
        --max-time 10 \
        "${server_url}/provisioning/heartbeat" 2>/dev/null)

    if [ $? -eq 0 ] && echo "$response" | grep -q "server_time"; then
        # Check for pending commands
        local commands
        commands=$(echo "$response" | sed -n 's/.*"commands":\[\([^]]*\)\].*/\1/p')
        if [ -n "$commands" ] && [ "$commands" != "" ]; then
            process_commands "$commands"
        fi
        return 0
    fi
    return 1
}

process_commands() {
    local commands="$1"
    # Process commands from server (reboot, update, etc.)
    if echo "$commands" | grep -q '"reboot"'; then
        log "WARN" "Reboot command received from server"
        sync
        sleep 2
        reboot
    fi
}

# ── Main Loop ──
main() {
    mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$CONFIG_DIR/bin"
    echo $$ > "$PID_FILE"

    log "INFO" "TX3 Agent v$AGENT_VERSION starting..."
    log "INFO" "PID: $$"

    # Collect device identity
    collect_identity

    # Wait for network
    wait_for_network

    # Provision if needed
    if ! provision; then
        log "ERROR" "Provisioning failed, will retry on next boot"
        # Don't exit - keep trying
    fi

    # Start WireGuard
    if [ -f "$WG_CONFIG" ]; then
        start_wireguard || log "ERROR" "WireGuard start failed"
    fi

    # Start supervisor
    if [ -f "/system/bin/tx3-supervisor" ]; then
        /system/bin/tx3-supervisor &
        log "INFO" "Supervisor started"
    fi

    # Main heartbeat loop
    local heartbeat_interval
    heartbeat_interval=$(grep "^heartbeat_interval=" "$CONFIG_FILE" 2>/dev/null | cut -d= -f2-)
    heartbeat_interval=${heartbeat_interval:-$HEARTBEAT_INTERVAL}

    local consecutive_failures=0
    local wg_check_counter=0

    while true; do
        rotate_logs

        # Send heartbeat
        if send_heartbeat; then
            consecutive_failures=0
        else
            consecutive_failures=$((consecutive_failures + 1))
            if [ $consecutive_failures -ge 3 ]; then
                log "WARN" "Heartbeat failed $consecutive_failures times"
            fi
        fi

        # Check WireGuard every 5 heartbeats
        wg_check_counter=$((wg_check_counter + 1))
        if [ $wg_check_counter -ge 5 ]; then
            wg_check_counter=0
            if ! check_wireguard; then
                restart_wireguard
            fi
        fi

        # Re-provision if needed (config lost)
        if [ ! -f "$CONFIG_FILE" ] || ! grep -q "device_uuid" "$CONFIG_FILE" 2>/dev/null; then
            wait_for_network
            provision
            if [ -f "$WG_CONFIG" ]; then
                start_wireguard
            fi
        fi

        sleep "$heartbeat_interval"
    done
}

# ── Signal Handlers ──
cleanup() {
    log "INFO" "Agent shutting down..."
    rm -f "$PID_FILE"
    # Don't tear down WireGuard - let it persist for reconnect
    exit 0
}

trap cleanup INT TERM

# ── Entry Point ──
main "$@"
