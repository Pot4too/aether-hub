# Vývoj systému pre bezdrôtový zber a vyhodnocovanie dát
## Bachelor's Thesis — Technical Plan

---

## Project Overview

**Goal:** Design and implement a wireless sensor data collection system while analyzing the underlying WiFi communication stack.

**Two core deliverables:**
1. Functional hardware/software system (ESP32 → WiFi → RPi → Dashboard)
2. Analysis and documentation of the 802.11 WiFi layer enabling that system

---

## Hardware

- **Sensor node:** ESP32-C6 (WiFi 6 / 802.11ax)
  - Custom PCB with ESP32-C6-MINI-1 castellated module
  - Sensors: BME280 (temp, humidity, pressure), LiPo charging, USB-C
- **Server:** Raspberry Pi 4 running Raspberry Pi OS Lite 64-bit
- **Dev board:** ESP32-C6 Super Mini (prototyping)

---

## Software Stack

### ESP32 Firmware
- Framework: **ESP-IDF** (not Arduino)
- MQTT client: native `esp-mqtt` component
- WiFi: `esp_wifi_*` API with event loop logging
- Promiscuous mode: `esp_wifi_set_promiscuous()` for raw frame capture

### Raspberry Pi
- MQTT broker: **Mosquitto**
- Access point: **hostapd** + **dnsmasq**
- Dashboard: **Node-RED** (fast demo) or FastAPI + WebSockets (custom)
- WiFi visibility: `mac80211` kernel stack, `iw`, `tcpdump`, `Wireshark`

### Data Format & Topics
'''txt
sensors/<node_id>/temperature
sensors/<node_id>/humidity
sensors/<node_id>/pressure
sensors/<node_id>/status
'''

Payload: JSON, QoS 0 for sensor data, QoS 1 for status/events.

---

## WiFi Layer Analysis (Thesis Research Contribution)

### Capture & Observation Tools
- Wireshark on RPi — full 802.11 frame capture
- `iw` / `tcpdump` — association and DHCP tracing
- ESP-IDF WiFi event log — client-side state visibility
- `esp_wifi_set_promiscuous()` — raw frame inspection on ESP32

### 802.11 Flow to Document
1. **Probe Request / Response** — discovery
2. **Authentication** — open system
3. **Association Request / Response** — capability negotiation
4. **DHCP** — IP assignment over the new link
5. **MQTT connect** — application layer on top

### mac80211 Analysis Slice
- Focus: **association state machine** within Linux mac80211
- Map kernel subsystem blocks to 802.11 standard (IEEE 802.11-2020)
- Show what ESP-IDF `esp_wifi_connect()` abstracts on the client side
- Reference: openofdm (GitHub), mac80211 source, *802.11 Wireless Networks: The Definitive Guide* (Gast)

---

## Thesis Structure (Suggested)

1. Introduction & motivation
2. 802.11 standard overview — relevant layers and mechanisms
3. Hardware design — ESP32-C6 node, PCB, sensors
4. Firmware — ESP-IDF, WiFi stack, MQTT pipeline
5. Server infrastructure — RPi, hostapd, Mosquitto, dashboard
6. WiFi layer analysis — captured frames, state machine, mac80211 breakdown
7. Results & evaluation
8. Conclusion

---

## Tools & References

| Tool | Purpose |
|------|---------|
| ESP-IDF + PlatformIO | Firmware development |
| KiCad | PCB design |
| Wireshark / tcpdump | Frame capture & analysis |
| Node-RED | Dashboard |
| Mosquitto | MQTT broker |
| hostapd + mac80211 | Controlled AP + kernel WiFi stack |
| openofdm (GitHub) | 802.11 PHY/MAC reference |
| Gast — 802.11 Definitive Guide | Primary literature |
