# Nextcloud Talk ↔ Slack Bridge

A bidirectional bridge between Nextcloud Talk and Slack, built with FastAPI, PostgreSQL, and Redis.

## Features
- Bidirectional text and emoji synchronization.
- **Phase 2:** Bidirectional reaction syncing (12 core emojis).
- **Phase 2:** Scaling to multiple channels (Dynamic routing via Database).
- HMAC-SHA256 signature verification for security.
- Redis-based deduplication to prevent message loops.
- PostgreSQL for user/channel mapping, message tracking, and audit logs.
- Isolated file event routing to dedicated "file sink" channels.

## Tech Stack
- **Backend:** Python 3.12+, FastAPI
- **Database:** PostgreSQL (SQLAlchemy Async)
- **Cache:** Redis
- **Containerization:** Docker & Docker Compose

## Getting Started

### Prerequisites
- Docker and Docker Compose installed.
- Slack App with Events API enabled (`message.channels`, `reaction_added`, `reaction_removed` scopes).
- Nextcloud Talk with bot access.

### Setup
1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in credentials.
3. Get your Slack Bot User ID (optional but recommended for loop prevention):
   ```bash
   python scripts/get_bot_id.py
   ```
4. Build and start the containers:
   ```bash
   docker-compose up --build
   ```

### Management & Scaling
Phase 2 supports dynamic routing for multiple channels. Import your mappings using CSV:

```bash
# Import users
docker-compose exec app python scripts/import_mappings.py user user_mapping.csv

# Import 42 channels for scaling
docker-compose exec app python scripts/import_mappings.py channel channel_mapping.csv
```

## Architecture
See the [Implementation Plan](plans/implementation_plan.md) for Phase 2 architectural details.
