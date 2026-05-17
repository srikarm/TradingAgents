#!/usr/bin/env bash
set -euo pipefail
# Run alembic, then seed Postgres + filesystem fixture.
docker compose exec -T api uv run alembic upgrade head
docker compose exec -T db psql -U trading -d trading_dashboard < seed.sql

USER_DIR=/data/users/11111111-2222-3333-4444-555555555555/NVDA/2024-05-10
docker compose exec -T api sh -c "
  mkdir -p ${USER_DIR}/reports/1_analysts &&
  echo '# market — NVDA' > ${USER_DIR}/reports/1_analysts/market.md &&
  echo '# final — BUY' > ${USER_DIR}/reports/final_trade_decision.md
"
