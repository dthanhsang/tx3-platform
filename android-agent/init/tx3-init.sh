#!/system/bin/sh
# TX3 Remote Management - Android Init Script
# Placed at /system/bin/preinstall.sh or /system/etc/init.d/
# Auto-starts all TX3 services on boot
#
# Version: 1.0.0

# Wait for boot completion
i=0
while [ "$(getprop sys.boot_completed)" != "1" ] && [ $i -lt 120 ]; do
    sleep 2
    i=$((i + 1))
done

# Wait for network to be ready
sleep 5

CONFIG_DIR="/data/tx3"
LOG_DIR="$CONFIG_DIR/logs"
BIN_DIR="/system/bin"

# Ensure directories exist
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$CONFIG_DIR/bin"

# ── Auto-enable ADB over network ──
# Enable ADB debugging
setprop persist.sys.usb.config adb
setprop service.adb.tcp.port 5555

# Restrict ADB to WireGuard interface only (will be configured after WG starts)
# Default: enable ADB for initial setup
settings put global adb_enabled 1 2>/dev/null
setprop persist.adb.tcp.enable 1

# Restart ADB daemon to pick up TCP settings
stop adbd 2>/dev/null
start adbd 2>/dev/null

echo "[$(date)] ADB enabled on port 5555" >> "$LOG_DIR/init.log"

# ── Start TX3 Agent ──
if [ -f "$BIN_DIR/tx3-agent" ]; then
    # Check if already running
    if [ -f "$CONFIG_DIR/tx3-agent.pid" ]; then
        old_pid=$(cat "$CONFIG_DIR/tx3-agent.pid")
        if kill -0 "$old_pid" 2>/dev/null; then
            echo "[$(date)] TX3 Agent already running (PID: $old_pid)" >> "$LOG_DIR/init.log"
        else
            rm -f "$CONFIG_DIR/tx3-agent.pid"
            "$BIN_DIR/tx3-agent" &
            echo "[$(date)] TX3 Agent started (PID: $!)" >> "$LOG_DIR/init.log"
        fi
    else
        "$BIN_DIR/tx3-agent" &
        echo "[$(date)] TX3 Agent started (PID: $!)" >> "$LOG_DIR/init.log"
    fi
else
    echo "[$(date)] ERROR: tx3-agent not found at $BIN_DIR/tx3-agent" >> "$LOG_DIR/init.log"
fi

echo "[$(date)] TX3 Remote Management init complete" >> "$LOG_DIR/init.log"
