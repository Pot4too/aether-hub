#!/usr/bin/env bash
# Dual-WiFi setup for the Pi (Raspberry Pi OS Bookworm / NetworkManager):
#   onboard WiFi -> access point for IoT nodes
#   USB adapter  -> client; joins the highest-priority known network in range
#
# All settings live in scripts/wifi.conf (copy from wifi.conf.example).
# The script is idempotent: edit the config, run `apply` again, done.
#
# Usage (run on the Pi):
#   sudo scripts/wifi-setup.sh apply          create/update all profiles and bring them up
#   sudo scripts/wifi-setup.sh status         show devices, connections, routes
#   sudo scripts/wifi-setup.sh prefer         switch back to the best uplink if a lower one is active
#   sudo scripts/wifi-setup.sh install-timer  run `prefer` every 2 min via systemd
#   sudo scripts/wifi-setup.sh remove         delete the profiles defined in the config

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${WIFI_CONF:-${SCRIPT_DIR}/wifi.conf}"

UPLINK_NAMES=(); UPLINK_SSIDS=(); UPLINK_PASSES=(); UPLINK_PRIOS=()
uplink() {
    UPLINK_NAMES+=("$1"); UPLINK_SSIDS+=("$2"); UPLINK_PASSES+=("$3"); UPLINK_PRIOS+=("$4")
}

[[ -f "$CONF" ]] || { echo "Missing $CONF — copy wifi.conf.example and edit it." >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONF"

need_root() { [[ "$(id -u)" -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }; }

con_exists() { nmcli -t -f NAME con show | grep -Fxq "$1"; }

# Delete-and-recreate keeps the script simple and makes config edits always win.
recreate() { con_exists "$1" && nmcli con delete "$1" >/dev/null; true; }

# Echo the MAC-binding args for a profile, or nothing if binding by name.
bind_args() {
    local mac="$1"
    [[ -n "$mac" ]] && echo "802-11-wireless.mac-address $mac"
    return 0
}

apply_ap() {
    echo "==> AP profile '${AP_CON_NAME}' (${AP_SSID})"
    recreate "$AP_CON_NAME"
    local ifname_args=()
    [[ -z "$AP_MAC" ]] && ifname_args=(ifname "$AP_IFACE")
    # shellcheck disable=SC2046
    nmcli con add type wifi con-name "$AP_CON_NAME" "${ifname_args[@]}" ssid "$AP_SSID" \
        connection.autoconnect yes \
        802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel "$AP_CHANNEL" \
        $(bind_args "$AP_MAC") \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$AP_PASSPHRASE" \
        ipv4.method shared ipv4.addresses "$AP_IP" ipv6.method disabled >/dev/null
}

apply_uplinks() {
    local i metric
    # Sort by priority is implicit: metric follows priority rank.
    local order
    order=$(for i in "${!UPLINK_NAMES[@]}"; do echo "${UPLINK_PRIOS[$i]} $i"; done | sort -rn | awk '{print $2}')
    local rank=0
    for i in $order; do
        metric=$((UPLINK_METRIC_BASE + rank * 100))
        echo "==> Uplink '${UPLINK_NAMES[$i]}' (${UPLINK_SSIDS[$i]}) priority=${UPLINK_PRIOS[$i]} metric=${metric}"
        recreate "${UPLINK_NAMES[$i]}"
        local ifname_args=()
        [[ -z "$UPLINK_MAC" ]] && ifname_args=(ifname "$UPLINK_IFACE")
        # shellcheck disable=SC2046
        nmcli con add type wifi con-name "${UPLINK_NAMES[$i]}" "${ifname_args[@]}" ssid "${UPLINK_SSIDS[$i]}" \
            connection.autoconnect yes \
            connection.autoconnect-priority "${UPLINK_PRIOS[$i]}" \
            connection.autoconnect-retries 0 \
            $(bind_args "$UPLINK_MAC") \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "${UPLINK_PASSES[$i]}" \
            ipv4.route-metric "$metric" >/dev/null
        rank=$((rank + 1))
    done
}

cmd_apply() {
    need_root
    apply_ap
    apply_uplinks
    echo "==> Bringing connections up"
    nmcli con up "$AP_CON_NAME" || echo "AP did not come up (is the adapter present?)" >&2
    # Let NetworkManager pick the best uplink in range via autoconnect priority.
    nmcli device connect "${UPLINK_IFACE}" 2>/dev/null || true
    echo
    cmd_status
}

cmd_status() {
    nmcli device status
    echo; nmcli con show --active
    echo; ip route
}

# Priority only matters at connect time, so NetworkManager won't hop back to
# home while on the phone hotspot. This tries the best profile that is in range.
cmd_prefer() {
    need_root
    local active best="" best_prio=-1 i
    active=$(nmcli -t -f NAME,DEVICE con show --active | awk -F: -v d="$UPLINK_IFACE" '$2==d{print $1}')
    for i in "${!UPLINK_NAMES[@]}"; do
        if (( UPLINK_PRIOS[i] > best_prio )); then best="${UPLINK_NAMES[$i]}"; best_prio=${UPLINK_PRIOS[$i]}; fi
    done
    [[ -n "$best" && "$active" != "$best" ]] || exit 0
    nmcli device wifi rescan ifname "$UPLINK_IFACE" 2>/dev/null || true
    if nmcli -t -f SSID device wifi list ifname "$UPLINK_IFACE" | grep -Fxq "$(ssid_of "$best")"; then
        echo "Switching uplink ${active:-none} -> ${best}"
        nmcli con up "$best" || true
    fi
}

ssid_of() {
    local i
    for i in "${!UPLINK_NAMES[@]}"; do
        [[ "${UPLINK_NAMES[$i]}" == "$1" ]] && { echo "${UPLINK_SSIDS[$i]}"; return; }
    done
}

cmd_install_timer() {
    need_root
    local script="${SCRIPT_DIR}/wifi-setup.sh"
    cat > /etc/systemd/system/aether-wifi-prefer.service <<EOF
[Unit]
Description=Switch back to preferred WiFi uplink

[Service]
Type=oneshot
Environment=WIFI_CONF=${CONF}
ExecStart=${script} prefer
EOF
    cat > /etc/systemd/system/aether-wifi-prefer.timer <<EOF
[Unit]
Description=Periodically prefer the best WiFi uplink

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now aether-wifi-prefer.timer
    echo "Timer installed. Check: systemctl list-timers aether-wifi-prefer.timer"
}

cmd_remove() {
    need_root
    local n
    for n in "$AP_CON_NAME" "${UPLINK_NAMES[@]}"; do
        con_exists "$n" && { echo "deleting $n"; nmcli con delete "$n" >/dev/null; }
    done
    return 0
}

case "${1:-}" in
    apply)         cmd_apply ;;
    status)        cmd_status ;;
    prefer)        cmd_prefer ;;
    install-timer) cmd_install_timer ;;
    remove)        cmd_remove ;;
    *) sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 1 ;;
esac
