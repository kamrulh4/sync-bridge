# Nextcloud Talk ↔ Slack Bridge

A bidirectional bridge between Nextcloud Talk and Slack, built with FastAPI, PostgreSQL, and Redis.

## Features
- Bidirectional text and emoji synchronization.
- HMAC-SHA256 signature verification for security.
- Redis-based deduplication to prevent message loops.
- PostgreSQL for user/channel mapping and audit logs.
- Isolated file event routing to dedicated "file sink" channels.

## Tech Stack
- **Backend:** Python 3.12+, FastAPI
- **Database:** PostgreSQL (SQLAlchemy Async)
- **Cache:** Redis
- **Containerization:** Docker & Docker Compose

## Getting Started

### Prerequisites
- Docker and Docker Compose installed.
- Slack App with Events API enabled.
- Nextcloud Talk with bot access.

### Setup
1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in any missing credentials.
3. Build and start the containers:
   ```bash
   docker-compose up --build
   ```
4. Load user mappings:
   ```bash
   docker-compose exec app python scripts/import_mappings.py user_mapping.csv
   ```

## Development

### Running Tests
To run the automated test suite inside the Docker container:
```bash
docker-compose exec app pytest
```

### Importing Mappings
Once you have the CSV files, import them using the following commands:
```bash
# Import users
docker-compose exec app python scripts/import_mappings.py user user_mapping.csv

# Import channels (if needed for Phase 2)
docker-compose exec app python scripts/import_mappings.py channel channel_mapping.csv
```

See the [Implementation Plan](plans/implementation_plan.md) for architectural details.
