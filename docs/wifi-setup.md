# WiFi setup — Pi as access point + wireless uplink

This is a **host OS** setup, not a Docker service. Access-point mode needs direct `wlan0`/nl80211 access that a container can't get cleanly, and it only needs to be done once during Pi provisioning.

Target: Raspberry Pi 4B, Raspberry Pi OS Lite 64-bit. This deployment runs **Bookworm**, where **NetworkManager** owns all interfaces by default, so the AP is an `nmcli` hotspot profile instead of hand-written `hostapd`/`dnsmasq` config files.

**Which section do you need?**

| I want to… | Read |
|---|---|
| Set the Pi up (recommended) | [Overview](#overview) → [Scripted setup](#scripted-setup-wifi-setupsh) |
| Understand or reproduce what the script does by hand | [Manual setup with `nmcli`](#manual-setup-with-nmcli) |
| Get the Pi online with no router or dongle | [Wired backup via laptop ICS](#wired-backup-via-laptop-internet-connection-sharing-ics) |
| Fix the Pi's clock | [NTP / wall-clock accuracy](#ntp--wall-clock-accuracy) |
| Set up on an older (dhcpcd) OS | [Legacy: hostapd + dnsmasq](#legacy-hostapd--dnsmasq-bullseye-and-earlier) |
| Know why the USB dongle doesn't work | [Hardware notes: AIC8800D80](#hardware-notes-aic8800d80-usb-adapter) |

## Overview

A single WiFi radio can only be tuned to one channel at a time, so `wlan0` can't simultaneously be a client on the home network *and* host the `aether-hub` access point for the sensor nodes — the Pi 4B's onboard chip doesn't reliably support concurrent AP+STA mode. Two separate physical interfaces are used instead:

- **`wlan0`** (onboard) — dedicated AP for the ESP32 sensor nodes (2.4 GHz; the ESP32-C6 nodes are 2.4 GHz-only).
- **A USB WiFi dongle** (`wlan1`) — client on the home WiFi network, used for SSH access, NTP and general internet uplink. It joins the highest-priority known network in range (home first, phone hotspot as fallback).
- **`eth0`** — backup path, used when the dongle isn't available or the home WiFi is down.

## Scripted setup (`wifi-setup.sh`)

Dual-WiFi setup for the Pi on Raspberry Pi OS Bookworm (NetworkManager). The AP uses `ipv4.method shared`, so nodes get DHCP and NAT.

All settings live in `scripts/wifi.conf`. The script is idempotent: edit the config, run `apply` again, and the profiles are recreated to match.

### First-time setup (on the Pi)

```bash
cp scripts/wifi.conf.example scripts/wifi.conf
nano scripts/wifi.conf                      # SSIDs, passwords, MACs
sudo scripts/wifi-setup.sh apply
sudo scripts/wifi-setup.sh install-timer    # optional, see "Switching back to home"
```

`wifi.conf` is gitignored because it contains passwords. Only `wifi.conf.example` is committed.

### Finding the MAC addresses

```bash
nmcli -f GENERAL.DEVICE,GENERAL.HWADDR device show
```

The onboard chip has a Raspberry Pi MAC prefix (`d8:3a:dd`, `dc:a6:32`, `e4:5f:01`). Put it in `AP_MAC` and the USB adapter's MAC in `UPLINK_MAC`. Binding by MAC stops `wlan0`/`wlan1` from swapping between boots. If both are left empty, the script binds by `AP_IFACE` / `UPLINK_IFACE` instead.

### Commands

| Command | What it does |
|---|---|
| `sudo scripts/wifi-setup.sh apply` | Create or update the AP and uplink profiles, then bring them up |
| `sudo scripts/wifi-setup.sh status` | Show devices, active connections and routes |
| `sudo scripts/wifi-setup.sh prefer` | Switch to the best uplink if a lower-priority one is active and the better one is in range |
| `sudo scripts/wifi-setup.sh install-timer` | Run `prefer` every 2 minutes via a systemd timer |
| `sudo scripts/wifi-setup.sh remove` | Delete the profiles defined in the config |

### Changing things later

Edit `scripts/wifi.conf`, then `sudo scripts/wifi-setup.sh apply`.

- **Add a network:** add a line such as `uplink cafe "SSID" "pass" 5`. A higher priority number is preferred.
- **Change the AP:** edit `AP_SSID`, `AP_PASSPHRASE`, `AP_CHANNEL` or `AP_IP`. Reapplying briefly drops the nodes.
- **Remove a network:** delete its line, then `sudo nmcli con delete <name>`. `apply` never deletes profiles that are no longer in the config.

Workflow: edit and push the script from your Mac, then on the Pi run `git pull && sudo scripts/wifi-setup.sh apply`. `wifi.conf` stays local to each machine.

### Verifying

```bash
nmcli con show --active
iw dev wlan0 info        # should say type AP
iw dev wlan1 link        # which SSID the USB adapter joined
ip route                 # home should have the lowest metric
```

To test the fallback, run `sudo nmcli con down home`, or switch off the home router. The Pi should join the phone hotspot.

### Switching back to home

Priority only applies when NetworkManager *connects*. If the Pi is on the phone hotspot and home WiFi comes back, it will not move on its own. `install-timer` installs a systemd timer (`aether-wifi-prefer.timer`) that runs `prefer` every 2 minutes, which moves it back once the better network is visible. Check it with `systemctl list-timers aether-wifi-prefer.timer`.

### Caveats

- **"In range but no internet" is not a failure** for NetworkManager. If home WiFi is up but its internet is down, the Pi stays on it.
- **Phone hotspots** often switch off when idle. Disable the hotspot's auto-off setting.
- **Channel conflict:** the AP is on 2.4 GHz channel 6. A 2.4 GHz uplink on a different channel can interfere with it. If the USB adapter supports 5 GHz, prefer 5 GHz networks for the uplinks.
- **Not tested on hardware yet.** The script was only syntax-checked. Run `apply` with the Pi on a keyboard and monitor, or over ethernet, in case the WiFi link you are SSH'd in on gets recreated.

## Manual setup with `nmcli`

The same result as the script, step by step. Useful for understanding what the script does or for a one-off setup.

### 1. USB WiFi dongle — home network client

Plug in the dongle and confirm NetworkManager sees it:

```bash
nmcli device status
```

It typically shows up as `wlan1` next to the onboard `wlan0`. Connect it to the home network:

```bash
sudo nmcli device wifi connect "<home-SSID>" password "<home-password>" ifname wlan1
```

Verify it has internet access before continuing.

### 2. `wlan0` — access point for sensor nodes

Since NetworkManager manages `wlan0` on this Pi, the AP is created as a hotspot connection profile:

```bash
sudo nmcli con add type wifi ifname wlan0 con-name aether-hub-ap autoconnect yes ssid aether-hub
sudo nmcli con modify aether-hub-ap 802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6
sudo nmcli con modify aether-hub-ap wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<passphrase>"
sudo nmcli con modify aether-hub-ap ipv4.method shared ipv4.addresses <AP_IP>/24
sudo nmcli con modify aether-hub-ap ipv6.method disabled
sudo nmcli con up aether-hub-ap
```

Replace `<passphrase>` and `<AP_IP>` with the values chosen for this deployment (the defaults in `scripts/wifi.conf.example` are SSID `aether-hub`, channel 6, `192.168.77.1`).

Notes:

- `ipv4.method shared` makes NetworkManager run its own internal DHCP server for AP clients (equivalent to what `dnsmasq` does in the legacy setup) and sets up NAT — meaning sensor nodes get internet access routed out through `wlan1`/`eth0` if they want it. This differs from the fully isolated network the legacy setup produces; not a problem for this project, just worth knowing.
- No need for `nmcli device set wlan0 managed no` — `wlan0` stays NetworkManager-managed, just as an AP profile instead of a client.

### 3. Verify both interfaces

```bash
nmcli con show --active     # aether-hub-ap on wlan0, home SSID on wlan1
iw dev wlan0 info           # should show type AP
```

## Wired backup via laptop Internet Connection Sharing (ICS)

If the USB dongle isn't available or the home WiFi is unreachable, a laptop can share its own WiFi connection to the Pi over a direct Ethernet cable — no router involved.

**Physical setup:** plug an Ethernet cable directly from the laptop to the Pi's `eth0` (use a USB-Ethernet adapter on the laptop if needed).

**On a Windows laptop:**

1. Open Network Connections (`ncpa.cpl`).
2. Right-click the WiFi adapter → **Properties** → **Sharing** tab.
3. Check **"Allow other network users to connect through this computer's Internet connection."**
4. In the dropdown, select the Ethernet adapter connected to the Pi.
5. Click OK.

Windows assigns `192.168.137.1` to that Ethernet adapter and hands out DHCP leases (`192.168.137.x`) to anything plugged into it, including the Pi.

**On the Pi:** nothing to configure — `eth0` is NetworkManager-managed and DHCP by default, so it picks up an address automatically once the cable is connected and ICS is enabled.

**Finding the Pi to SSH in**, from the laptop:

```powershell
arp -a | findstr 192.168.137
```

or, if mDNS/avahi is set up on the Pi:

```powershell
ssh pi@raspberrypi.local
```

Limitation: this path only works while the laptop is awake with WiFi connected and ICS enabled — it's a desk-side debug/backup connection, not suitable for unattended deployment.

## NTP / wall-clock accuracy

The ESP32 sensor nodes have no RTC, so `ingest` back-calculates reading timestamps from receipt time (see [mqtt-protocol.md](mqtt-protocol.md#wall-clock-dependency)), which makes the Pi's own clock accuracy matter.

- **With `wlan1` (or `eth0` via ICS) providing a real uplink**, the Pi has a normal path to NTP, so the wall-clock caveat doesn't apply as long as one of these paths is connected at least occasionally to keep the clock synced.
- **Try Ethernet-uplink-while-AP first.** The Pi 4B's Ethernet port and WiFi radio are separate physical interfaces, so running `wlan0` as an AP does not prevent using `eth0` for a normal uplink — including NTP. This is the easiest fix if you have a wired connection available where the Pi is deployed.
- **If genuinely offline**, set the clock manually before deployment:
  ```bash
  sudo timedatectl set-time '2026-08-22 12:00:00'
  ```
  and expect timestamps to drift afterward with no correction — a documented limitation, not a bug.

## Legacy: hostapd + dnsmasq (Bullseye and earlier)

Only relevant on an older OS where **dhcpcd** (not NetworkManager) owns `wlan0`. The previous `setup-ap_old.sh` automated these steps and has been removed; if you need it again, write a new script for your setup using the steps below.

### 1. Identify your networking stack first

Raspberry Pi OS Bookworm defaults to **NetworkManager**; Bullseye and earlier default to **dhcpcd**. The two are configured completely differently, and fighting each other is the most common cause of a flaky AP.

```bash
systemctl is-active NetworkManager   # active -> Bookworm-style
systemctl is-active dhcpcd           # active -> Bullseye-style
```

If NetworkManager owns `wlan0`, either tell it to ignore the interface (`nmcli device set wlan0 managed no`) or configure the AP as a NetworkManager connection profile instead of hand-writing `dhcpcd.conf`/`hostapd` — that is what the sections above do. The steps below assume the dhcpcd-style flow.

### 2. Install hostapd + dnsmasq

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq
sudo systemctl unmask hostapd
```

### 3. Static IP on wlan0

The AP interface needs a fixed address before dnsmasq can hand out leases from it. With dhcpcd:

```
# /etc/dhcpcd.conf
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
```

### 4. dnsmasq DHCP range

```
# /etc/dnsmasq.conf
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
```

### 5. hostapd.conf basics

```
# /etc/hostapd/hostapd.conf
interface=wlan0
driver=nl80211
ssid=<your SSID>
hw_mode=g                # 2.4GHz — the ESP32-C6 sensor nodes are 2.4GHz-only
channel=<your channel>
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=<your passphrase>
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
country_code=<your ISO country code>   # required — sets legal channel/power limits
```

Point `hostapd` at this file via `/etc/default/hostapd` (`DAEMON_CONF="/etc/hostapd/hostapd.conf"`).

### 6. Enable both services

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo systemctl restart dhcpcd
sudo systemctl start hostapd dnsmasq
```

### 7. Verify

```bash
iw dev wlan0 info           # should show type AP
sudo systemctl status hostapd dnsmasq
cat /var/lib/misc/dnsmasq.leases   # client leases as nodes join
```

### Monitor-mode adapter (thesis track — out of this repo's scope)

If you're also running a secondary USB WiFi adapter in monitor mode for 802.11 frame capture, make sure it stays **unmanaged** by NetworkManager and untouched by dhcpcd/hostapd — it's a separate physical interface doing passive capture, not part of the AP, and having either networking stack try to manage it will break the capture.

## Hardware notes: AIC8800D80 USB adapter

Status: **does not work on the Pi 4. Use a different adapter.**

Goal: use a second WiFi adapter as the uplink, with the onboard `wlan0` as the IoT access point. Configured through `scripts/wifi.conf` and `scripts/wifi-setup.sh`.

Environment: Raspberry Pi 4, Debian 13 (trixie), kernel `6.18.34+rpt-rpi-v8` (also built for `6.18.50`), arm64.

### Hardware

| Item | Value |
|---|---|
| Onboard WiFi | `wlan0`, MAC `DC:A6:32:xx:xx:xx` (use as `AP_MAC`) |
| USB adapter | AIC8800D80 |
| Storage-mode ID | `a69c:5723` ("Aic MSC", fake flash disk) |
| WiFi-mode ID | `a69c:8d80` ("AIC Wlan") |
| Expected runtime ID | `a69c:8d81` (never reached) |

`UPLINK_MAC` is still empty.

### What works

- **Mode switch** from `5723` to `8d80`. It needs two things:
  - The udev rule `/etc/udev/rules.d/40-aic8800.rules`, which runs `usb_modeswitch -KW -v a69c -p 5723`.
  - A quirk so the kernel's `usb-storage` driver doesn't claim the device first: `/etc/modprobe.d/aic-ignore-storage.conf` with `options usb-storage quirks=a69c:5723:i`.
  - Without the quirk the adapter got stuck in storage mode: every switch attempt timed out (libusb error -7) and no SCSI disk ever appeared.
- **Loader and firmware.** `aic_load_fw` detects the chip (`chip_id=7`), finds `/lib/firmware/aic8800_fw/USB/aic8800D80/`, and all four blobs upload (`fw_patch_table`, `fw_adid`, `fw_patch`, `fw_patch_ext0`, then `fmacfw_8800d80_u02.bin`), each reporting `fw download complete`.

### What fails

After the last firmware blob the loader calls `aicwf_bus_deinit`, logs a burst of `bus is not up` lines and ends with `aicwf_usb_probe ... failed with errno 0`. The chip never re-enumerates as `8d81`, so `aic8800_fdrv_usb` never binds and no `wlan1` appears.

By design the loader binds `8d80`, uploads firmware, and the chip restarts as `8d81`, which the WiFi driver then claims. In every tree we checked, the WiFi driver's ID table has no `8d80` entry (only `8d81`, `8d41`, `88dc`, `8801` and others), so a stuck-at-`8d80` chip can never be picked up.

### Drivers tried

| Driver | Result |
|---|---|
| `kilam994/aic8800d80-linux-driver` (DKMS) | Interface stayed on the loader. Binding the WiFi module returned "No such device". Using `new_id` caused a NULL dereference in `aicwf_usb_free_urb`, wedged the module and hung the reboot (power cycle needed). |
| `radxa-pkg/aic8800` (`make deb`, firmware plus USB DKMS packages) | Builds and installs cleanly on 6.18. Same stall after the firmware upload. No crash. |
| `shenmintao/aic8800d80` | Not installed. Its D80 firmware is byte-identical to radxa's and its WiFi driver ID table has the same entries, so the result would be the same. |

Other things tried without effect: software USB reset of the adapter, a different USB port, a reboot, and `usb_max_current_enable=1` in `config.txt`. A powered USB hub was not tested, and the `vcgencmd get_throttled` value was not recorded.

### Notes for next time

- Build the radxa packages with:
  ```
  sudo apt install -y git build-essential dkms debhelper devscripts fakeroot dh-exec dh-dkms linux-headers-rpi-v8
  git clone --recurse-submodules https://github.com/radxa-pkg/aic8800.git
  cd aic8800 && make deb
  ```
  The final lintian step fails on cosmetic warnings (`aliased-location`, old FSF address). The `.deb` files are still produced in the parent directory and can be installed anyway.
- Do not use `new_id` or manual `bind` for this chip. That is what crashed the first driver.
- The WiFi module for this package is named `aic8800_fdrv_usb` and the loader `aic_load_fw_usb`, not `aic8800_fdrv`.
- `sudo` is needed for `dkms`, `modinfo` and `usb_modeswitch`, because `/usr/sbin` isn't on the user's `PATH`.
- When pasting commands into zsh, leave out `#` comments.

### Decision

Replace the adapter with one that has an in-kernel driver (`mt76`): **MT7612U** (dual-band) or **MT7921AU** (WiFi 6). Check the chipset on the listing before buying, because many listings reuse a product name with a different chip.

#### Cleanup after giving up on the AIC adapter

```
sudo apt remove aic8800-usb-dkms aic8800-firmware
sudo rm -f /etc/modprobe.d/aic-ignore-storage.conf /etc/udev/rules.d/40-aic8800.rules
sudo dkms status
rm -rf ~/aic8800 ~/aic8800d80 ~/radxa-fw ~/*.deb
```

#### Setup with the new adapter

1. Plug it in and find the MAC: `nmcli -f GENERAL.DEVICE,GENERAL.HWADDR device show`
2. In `scripts/wifi.conf` set `AP_MAC="DC:A6:32:xx:xx:xx"` and `UPLINK_MAC` to the new adapter's MAC.
3. Apply: `sudo scripts/wifi-setup.sh apply`
4. Check: `nmcli connection show`, `nmcli device status`, `ip route`. Expected: `wlan0` runs the AP at `192.168.77.1`, the new adapter holds the uplink and the default route.
