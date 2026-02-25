# plow-agent

A lightweight agent that helps [Where the Plow](https://plow.jackharrhy.dev) collect snowplow GPS data from the City of St. John's.

## Why?

The city publishes real-time plow locations on their [AVL map](https://map.stjohns.ca/avl/), but their firewall blocks automated requests from server IPs. By running this agent on your own machine or home server, you contribute your residential IP to a pool of volunteers that fetch the data on behalf of the tracking service. The more people running the agent, the more resilient the data collection becomes.

## How it works

1. On first run, the agent generates a cryptographic keypair and registers itself with the plow server.
2. You wait for the server operator to approve your agent (this is manual -- only trusted volunteers are approved).
3. Once approved, the agent periodically fetches plow data from the city's public map and reports it to the plow server, signed with its key.
4. The server coordinates all active agents so they take turns fetching, spreading the load across IPs.

Your credentials are stored locally and reused on subsequent runs. The agent uses minimal resources and runs quietly in the background.

## Quick start (recommended)

Download the latest release for your platform, then just run it:

```
./plow-agent
```

This launches an interactive setup wizard that:
1. Asks for the server URL (defaults to `https://plow.jackharrhy.dev`)
2. Prompts for a name to identify your agent (e.g. "alice-laptop")
3. Generates your cryptographic keypair
4. Registers with the server
5. Installs itself as a **system service** (systemd on Linux, launchd on macOS, Windows service)
6. Starts the service automatically

After setup, the agent runs in the background and survives reboots. You don't need to keep a terminal open.

**Note:** Installing a system service requires administrator/root privileges. The wizard will prompt for your sudo password automatically. On Windows, run as Administrator.

**Once you see "Registered" in the output, let Jack know** (message him or open an issue) so he can approve your agent. It won't start fetching data until approved.

## Running interactively

If you prefer not to install a service (or for Docker/development use):

```
./plow-agent --run --server https://plow.jackharrhy.dev
```

This runs the agent in the foreground. Press Ctrl+C to stop.

## Managing the service

Once installed, you can control the service with:

```
plow-agent --service status      # Check if running + platform info
plow-agent --service logs        # View live logs (auto-detects platform)
plow-agent --service stop        # Stop the service
plow-agent --service start       # Start the service
plow-agent --service restart     # Restart the service
plow-agent --service uninstall   # Remove the service
```

The `status` and `logs` commands automatically detect your platform and show the right information -- no need to remember platform-specific log commands.

### Complete removal

To fully uninstall the agent and clean up all its data:

```bash
# 1. Stop and remove the system service
plow-agent --service uninstall

# 2. Remove service data (credentials used by the daemon)
sudo rm -rf /var/lib/plow-agent

# 3. Remove your local config (keypair and name)
rm -rf ~/.config/plow-agent

# 4. Remove the binary itself
rm plow-agent
```

On macOS, if the service is stuck, you can force-remove it:

```bash
sudo launchctl bootout system/plow-agent
sudo rm /Library/LaunchDaemons/plow-agent.plist
```

## Docker / Docker Compose

The agent Docker image is published to `ghcr.io/jackharrhy/plow-agent` automatically on every release.

The easiest way to run it is with the included [`compose.yml`](compose.yml):

1. Download it: `curl -O https://raw.githubusercontent.com/jackharrhy/where-the-plow/main/agent/compose.yml`
2. Edit `PLOW_NAME` to something that identifies you (e.g. "alice-homelab")
3. Run it:

```bash
docker compose up -d
```

That's it. The volume keeps your keypair across restarts. Let Jack know once it's running so he can approve your agent.

To view logs:

```bash
docker compose logs -f
```

To stop and remove:

```bash
docker compose down
docker volume rm plow-agent_plow-agent-data  # removes credentials
```

### Docker run (without Compose)

```bash
docker run -d \
  --name plow-agent \
  --restart unless-stopped \
  -e PLOW_SERVER=https://plow.jackharrhy.dev \
  -e PLOW_NAME=your-name-here \
  -e PLOW_DATA_DIR=/data \
  -v plow-agent-data:/data \
  ghcr.io/jackharrhy/plow-agent:latest
```

### Building locally

```bash
docker build -t plow-agent agent/
```

## Kubernetes

A ready-made manifest is included at [`k8s.yaml`](k8s.yaml). Edit `PLOW_NAME` to your name, then:

```
kubectl apply -f agent/k8s.yaml
```

This creates a small PVC for key persistence and a Deployment running the agent.

## Configuration

| Flag / Env Var | Required | Description |
|---|---|---|
| `--server` / `PLOW_SERVER` | Yes (for `--run`) | Plow server URL |
| `--run` | No | Run in foreground instead of installing as service |
| `--service <action>` | No | Control installed service: install, uninstall, start, stop, restart, status, logs |
| `PLOW_NAME` | Docker/K8s only | Agent name (binary prompts interactively) |
| `PLOW_DATA_DIR` | No | Override config directory (default: `~/.config/plow-agent/`, or `/data` when set) |

## What gets stored

The agent stores two files:

- `key.pem` -- your ECDSA private key (never sent to the server, only used to sign requests)
- `name` -- the name you chose for this agent

**Interactive / `--run` mode:** stored in `~/.config/plow-agent/`

**System service:** stored in `/var/lib/plow-agent/` (copied there during install so the daemon can access them as root)

**Docker/K8s:** stored in the `/data` volume

## Checking your status

The agent logs its current status on startup and during operation:

```
2026/02/25 14:30:00 Agent ID: a1b2c3d4e5f67890
2026/02/25 14:30:01 Registered: agent_id=a1b2c3d4e5f67890 status=pending
2026/02/25 14:30:01 Status: pending — waiting for approval (checking every 30s)
```

Once Jack approves your agent:

```
2026/02/25 14:35:01 Approved! Fetching every 18s (offset 6s)
```
