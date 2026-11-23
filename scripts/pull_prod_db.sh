#!/usr/bin/env bash
# Dump the production database on the server, copy the dump to ./backups/,
# and restore it into the local dev database (docker-compose.dev.yml).
#
# Usage: scripts/pull_prod_db.sh [-y]
#   -y   skip the "this will wipe your local DB" confirmation
#
# The local database is DROPPED and recreated. Dumps land in backups/, which
# is gitignored — never commit them.
#
# Server details live in .env.scripts (gitignored); copy .env.scripts.example
# to .env.scripts and fill it in.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DIR="$REPO_ROOT/backups"
cd "$REPO_ROOT"

if [[ ! -f .env.scripts ]]; then
    echo "Missing .env.scripts — copy .env.scripts.example and fill it in." >&2
    exit 1
fi
set -a
# shellcheck source=/dev/null
source .env.scripts
set +a

SSH_HOST="${PROD_SSH_HOST:?PROD_SSH_HOST is not set in .env.scripts}"
REMOTE_DIR="${PROD_BACKUP_DIR:?PROD_BACKUP_DIR is not set in .env.scripts}"
REMOTE_CONTAINER="${PROD_DB_CONTAINER:?PROD_DB_CONTAINER is not set in .env.scripts}"
LOCAL_CONTAINER="${LOCAL_DB_CONTAINER:?LOCAL_DB_CONTAINER is not set in .env.scripts}"

ASSUME_YES=0
[[ "${1:-}" == "-y" ]] && ASSUME_YES=1

# Local DB name/user from .env, matching docker-compose.dev.yml defaults.
env_value() {
    grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d "\"'" || true
}
LOCAL_DB="$(env_value DB_NAME)"; LOCAL_DB="${LOCAL_DB:-qadam}"
LOCAL_USER="$(env_value DB_USER)"; LOCAL_USER="${LOCAL_USER:-qadam}"

# Don't bind any LocalForwards the ssh config defines for this host.
SSH_OPTS=(-o ClearAllForwardings=yes)

FILE="qadam_$(date +%Y%m%d_%H%M).dump"

echo "==> Dumping production DB on $SSH_HOST to $REMOTE_DIR/$FILE"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" bash -s -- "$REMOTE_DIR" "$FILE" "$REMOTE_CONTAINER" <<'REMOTE'
set -euo pipefail
dir="$1"; file="$2"; container="$3"
mkdir -p "$dir"
# Write to a temp name so a failed dump never leaves a truncated .dump behind.
docker exec "$container" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dir/$file.partial"
mv "$dir/$file.partial" "$dir/$file"
ls -lh "$dir/$file"
REMOTE

echo "==> Copying dump to $LOCAL_DIR/"
mkdir -p "$LOCAL_DIR"
scp "${SSH_OPTS[@]}" "$SSH_HOST:$REMOTE_DIR/$FILE" "$LOCAL_DIR/$FILE"

if [[ $ASSUME_YES -ne 1 ]]; then
    read -r -p "==> Drop and replace local database '$LOCAL_DB' with this dump? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted. Dump kept at backups/$FILE"; exit 0; }
fi

echo "==> Ensuring local dev database container is up"
docker compose -f docker-compose.dev.yml up -d db
until docker exec "$LOCAL_CONTAINER" pg_isready -U "$LOCAL_USER" >/dev/null 2>&1; do
    sleep 1
done

echo "==> Recreating local database '$LOCAL_DB'"
docker exec "$LOCAL_CONTAINER" dropdb -U "$LOCAL_USER" --if-exists --force "$LOCAL_DB"
docker exec "$LOCAL_CONTAINER" createdb -U "$LOCAL_USER" -O "$LOCAL_USER" "$LOCAL_DB"

echo "==> Restoring backups/$FILE into '$LOCAL_DB'"
if ! docker exec -i "$LOCAL_CONTAINER" pg_restore -U "$LOCAL_USER" -d "$LOCAL_DB" \
        --no-owner --no-privileges < "$LOCAL_DIR/$FILE"; then
    echo "!! pg_restore reported errors (see above); the restore may be incomplete." >&2
    exit 1
fi

echo "==> Done. Local '$LOCAL_DB' now matches production as of $FILE"
