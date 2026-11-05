#!/usr/bin/env bash
# Build and test the production image with a disposable database and random port.
# Run: sudo bash scripts/verify-container.sh
set -euo pipefail
cd "$(dirname "$0")/.."
check_suffix="$$-$RANDOM"
check_network="truecost-check-$check_suffix"
check_database="truecost-db-$check_suffix"
check_app="truecost-app-$check_suffix"
check_image="truecost-check:$check_suffix"
check_password="$(python3 -c 'import secrets; print(secrets.token_hex(20))')"
check_secret="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
cleanup() {
  docker rm -f "$check_app" "$check_database" >/dev/null 2>&1 || true
  docker network rm "$check_network" >/dev/null 2>&1 || true
  docker image rm "$check_image" >/dev/null 2>&1 || true
}
trap cleanup EXIT
printf 'Building the production image…\n'
docker build --tag "$check_image" .
docker network create "$check_network" >/dev/null
docker run --detach --name "$check_database" --network "$check_network" --network-alias db \
  --env POSTGRES_DB=truecost --env POSTGRES_USER=classroom --env POSTGRES_PASSWORD="$check_password" \
  --tmpfs /var/lib/postgresql/data postgres:17-alpine >/dev/null
check_ready=false
for check_attempt in $(seq 1 45); do
  if docker exec "$check_database" pg_isready -U classroom -d truecost >/dev/null 2>&1; then check_ready=true; break; fi
  sleep 1
done
if [ "$check_ready" != true ]; then printf 'Database startup failed.\n' >&2; exit 1; fi
docker run --detach --name "$check_app" --network "$check_network" --publish 127.0.0.1::8000 \
  --env "DATABASE_URL=postgresql+psycopg://classroom:$check_password@db:5432/truecost" \
  --env "INSTRUCTOR_SECRET=$check_secret" --env PORT=8000 "$check_image" >/dev/null
check_port="$(docker port "$check_app" 8000/tcp | head -1 | cut -d: -f2)"
check_ready=false
for check_attempt in $(seq 1 45); do
  if curl --fail --silent "http://127.0.0.1:$check_port/api/health" >/dev/null; then check_ready=true; break; fi
  sleep 1
done
if [ "$check_ready" != true ]; then printf 'Application startup failed; inspect the container build output.\n' >&2; exit 1; fi
if [ "$(docker exec "$check_app" id -u)" = 0 ]; then printf 'The application must run as a non-root user.\n' >&2; exit 1; fi
INSTRUCTOR_SECRET="$check_secret" python3 scripts/check_deployment.py "http://127.0.0.1:$check_port" --exercise-demo
printf 'PASS: production image served by a non-root user with disposable PostgreSQL.\n'
