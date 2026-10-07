# Starting and stopping the stack on the Pi

## How it behaves

| Situation | What happens |
|---|---|
| Pi boots | Docker starts, then brings up mosquitto, ingest and api automatically |
| `sudo poweroff` / `reboot` | systemd stops Docker, which sends SIGTERM to each container and waits up to 20 s (`stop_grace_period`) before killing it. Services shut down cleanly |
| You stop the stack manually | It stays stopped until you start it, **or until the next reboot or Docker restart**, when it comes back by itself |

This comes from `restart: always` in `docker-compose.yml`. The other common policy, `unless-stopped`, would keep a manually stopped stack stopped across reboots, which is not what we want here.

Your data (`./data`, or `AETHER_DATA_DIR`) is on the host and is never touched by stopping or starting.

## One-time setup on the Pi

Make sure Docker itself starts at boot:

```bash
sudo systemctl enable docker containerd
```

Then start the stack once so the containers exist:

```bash
scripts/start.sh
```

From now on it comes up on every boot with no further action. Test it with `sudo reboot`, then `docker compose ps` after about a minute.

## Normal operation

Nothing to do. Boot starts it and `sudo poweroff` stops it cleanly.

## Manual stop and start

```bash
scripts/stop.sh                # stop containers (kept, not removed)
scripts/start.sh               # start again (rebuilds images if code changed)
scripts/start.sh --no-build    # start again, skip the rebuild
scripts/stop.sh --poweroff     # stop the stack, then power off the Pi
```

Other useful commands, run from the repo root:

```bash
docker compose ps              # status
docker compose logs -f ingest  # follow one service's logs
docker compose restart api     # restart a single service
docker compose down            # stop AND remove containers (data is kept)
```

Use `stop` for pauses and poweroff. Use `down` only if you want containers removed, for example after editing the compose file's service definitions.

## Code changes

After `git pull`, run `scripts/start.sh`. It rebuilds the images and recreates only the containers that changed.

## Why shutdown is clean

- `docker stop` sends SIGTERM. The `ingest` service handles it: it disconnects from MQTT, closes the SQLite connection and exits. Without the handler, Python as PID 1 ignores SIGTERM and Docker kills it after the timeout.
- uvicorn (`api`) and mosquitto handle SIGTERM themselves.
- Each batch is committed to SQLite as it arrives, so a hard power cut loses at most the batch in flight. Pulling the plug is still worse for the SD card than a proper `poweroff`.

## Troubleshooting

- **Containers did not come back after boot:** check `systemctl is-enabled docker` and `docker compose ps -a`. If the containers don't exist yet (fresh SD card), run `scripts/start.sh` once.
- **Stack came up before the WiFi AP:** harmless. Nodes retry and reconnect on their own.
- **Poweroff takes longer than expected:** a service ignoring SIGTERM costs up to 20 s. Check with `journalctl -b -1 -u docker` after the next boot.

## Mac aliases (development only)

On your Mac, a `~/.zshrc` alias to stop every running container:

```zsh
dstop() { local ids; ids=$(docker ps -q); [[ -n "$ids" ]] && docker stop ${=ids} || echo "no running containers"; }
```

On the Pi, use `scripts/stop.sh` instead.
