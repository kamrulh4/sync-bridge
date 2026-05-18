# Nextcloud Talk ↔ Slack Bridge

A bidirectional bridge between Nextcloud Talk and Slack, built with FastAPI, PostgreSQL, and Redis.

## Features
- **Bidirectional Message Sync:** Real-time text and emoji synchronization between platforms.
- **Phase 2 - Reaction Sync:** Bidirectional synchronization of emoji reactions (`👍`, `❤️`, `✅`, etc.).
- **Phase 2 - Multi-Channel Scaling:** Dynamic routing via Database supporting 42+ channels.
- **Phase 2 - Global File Sink:** Isolated file event routing to dedicated central "file sink" channels/rooms.
- **Security:** HMAC-SHA256 signature verification for all incoming webhooks (`X-Slack-Signature` & `X-Nextcloud-Talk-Signature`).
- **Reliability:** Redis-backed deduplication layer (TTL 60s) to prevent infinite message and reaction echo loops.
- **Audit & Management:** PostgreSQL for user/channel mapping, message tracking, and audit logs.

## Tech Stack
- **Backend:** Python 3.12+, FastAPI
- **Database:** PostgreSQL (SQLAlchemy Async)
- **Cache:** Redis
- **Containerization:** Docker & Docker Compose

---

## Getting Started

### Prerequisites
- Docker and Docker Compose installed.
- Slack App with bot token (`xoxb-...`) and signing secret.
- Nextcloud Talk server with CLI (`occ`) access.

---

## Platform Configuration

### 1. Slack App Setup (Event Subscriptions)
To enable real-time message, reaction, and file syncing from Slack to Nextcloud:
1. Go to [Slack API Dashboard](https://api.slack.com/apps) and select your app (**PPH Talk Bridge**).
2. On the left menu, click **Event Subscriptions** and toggle **Enable Events** to **On**.
3. In the **Request URL** field, enter your bridge endpoint:
   `https://sync-bridge.billsheba.com/slack/events`
4. Once verified, scroll down to **Subscribe to bot events** and add the following 4 required events:
   - `message.channels` (To sync public channel chat messages)
   - `file_shared` (To detect and sync file uploads to the Global File Sink)
   - `reaction_added` (To sync added emoji reactions)
   - `reaction_removed` (To sync removed emoji reactions)
5. Click **Save Changes** at the bottom.
6. Go to **Install App** on the left menu and click **Reinstall to Workspace** (or request Admin approval) to apply the new event scopes.

### 2. Nextcloud Talk Bot Setup (`occ` CLI)
To enable real-time message and reaction syncing from Nextcloud Talk to Slack, you must install the bot on the Nextcloud server with the correct feature flags (`-f webhook -f response -f reaction`).

Log into your Nextcloud server terminal (or enter the Nextcloud Docker container) and run:

```bash
# Example command inside the Nextcloud Docker container:
docker exec -it <nextcloud_container> php occ talk:bot:install "PPH Bridge Bot" "YOUR_SHARED_HMAC_SECRET" "https://sync-bridge.billsheba.com/nextcloud/webhook" -f webhook -f response -f reaction
```

*(**Note:** Replace `YOUR_SHARED_HMAC_SECRET` with the exact secret from your bridge `.env` file).*

After installing, list your bots to find the new Bot ID:
```bash
docker exec -it <nextcloud_container> php occ talk:bot:list
```

Assign the bot to your Nextcloud Talk room (e.g., `hybvehsr`):
```bash
docker exec -it <nextcloud_container> php occ talk:bot:setup <bot_id> hybvehsr
```

---

## Deployment & Setup

1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in your credentials.
3. Get your Slack Bot User ID (optional but recommended for loop prevention):
   ```bash
   python scripts/get_bot_id.py
   ```
4. Build and start the bridge containers:
   ```bash
   docker-compose up -d --build
   ```

By default, the app will auto-import `user_mapping.csv`, `channel_mapping.csv`, and `filesink_mapping.csv` from the repo root when it starts.

---

## Management & Scaling (Phase 2)

Phase 2 supports dynamic routing for 42+ channels and Global File Sinks. You can import your mappings via CSV:

```bash
# Import user mappings
docker-compose exec app python scripts/import_mappings.py user user_mapping.csv

# Import 42 channels for scaling
docker-compose exec app python scripts/import_mappings.py channel channel_mapping.csv

# Import Global File Sink configuration
docker-compose exec app python scripts/import_mappings.py filesink filesink_mapping.csv
```

You can also manage mappings at runtime via the REST API without restarting the service:

- `POST /mapping/user` with `{ "external_id": "U123", "internal_id": "john.doe" }`
- `POST /mapping/channel` with `{ "external_id": "C12345678", "internal_id": "hybvehsr" }`
- `POST /mapping/import?type=user` with `{ "csv_content": "..." }`
- `POST /mapping/import?type=channel` with `{ "csv_content": "..." }`

---

## Architecture & Verification
For full architectural details and step-by-step testing checklists, refer to the documentation in the `plans/` directory:
- [Final Testing Checklist (Bengali)](plans/final_testing_steps_bn.md)
- [Real-Time Testing Guide](plans/realtime_testing_guide.md)
