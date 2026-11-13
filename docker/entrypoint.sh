#!/bin/sh
# Container entrypoint: one short command per common task.
set -e
cd /app

cmd="${1:-dashboard}"
[ $# -gt 0 ] && shift

case "$cmd" in
  dashboard)
    # Serve the repo root so dashboard/index.html can fetch results/*.json
    echo "Dashboard: http://localhost:${PORT:-8000}/dashboard/index.html"
    exec python -m http.server "${PORT:-8000}" --bind 0.0.0.0
    ;;
  test)
    exec python -m pytest -q "$@"
    ;;
  recorder)
    # Live Binance order-book + trade recorder. Default: every coin in config/candidates.txt
    if [ $# -eq 0 ]; then
      set -- --symbols-file config/candidates.txt
    fi
    exec python -m mm.recorder "$@"
    ;;
  module)
    # Run any module, e.g.:  module scripts.plot_quotes
    exec python -m "$@"
    ;;
  shell)
    exec /bin/bash
    ;;
  help|-h|--help)
    cat <<'EOF'
Commands:
  dashboard            serve the dashboard on port 8000 (default)
  test [pytest args]   run the test suite
  recorder [args]      record live order book (default: config/candidates.txt)
  module <name> [args] run any python module, e.g. module scripts.plot_quotes
                       testnet trader: module mm.testnet --symbols BTCUSDT --policy join
  shell                open a shell inside the container
  <anything else>      run as a plain command, e.g. python -c "..."
EOF
    ;;
  *)
    exec "$cmd" "$@"
    ;;
esac
