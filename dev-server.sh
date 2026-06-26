#!/bin/bash
# ExMint Dev Server Control — start/stop the dev test server
# Usage: ./dev-server.sh start|stop|restart|status

DEV_DIR="/home/mrar1995/dev/exmint"
PORT=5002
PID_FILE="$DEV_DIR/.dev-server.pid"
LOG_FILE="$DEV_DIR/.dev-server.log"

case "${1:-status}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
      echo "Dev server already running (PID $(cat $PID_FILE))"
      exit 0
    fi
    cd "$DEV_DIR"
    source venv/bin/activate
    nohup gunicorn --bind=0.0.0.0:$PORT --workers 2 --timeout 30 \
      --access-logfile - --error-logfile - "app:app" \
      > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if curl -s -o /dev/null -w "" http://localhost:$PORT/ 2>/dev/null; then
      echo "Dev server started on port $PORT (PID $(cat $PID_FILE))"
    else
      echo "Dev server failed to start — check $LOG_FILE"
      exit 1
    fi
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      kill $(cat "$PID_FILE") 2>/dev/null
      rm -f "$PID_FILE"
      echo "Dev server stopped"
    else
      echo "No dev server running"
    fi
    ;;
  restart)
    $0 stop
    sleep 1
    $0 start
    ;;
  status|*)
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
      echo "Dev server running on port $PORT (PID $(cat $PID_FILE))"
    else
      echo "Dev server not running"
    fi
    ;;
esac
