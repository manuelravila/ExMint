#!/bin/bash
source /code/ExMint/venv/bin/activate
export PYTHONUNBUFFERED=1


# Trim any leading or trailing whitespace from FLASK_ENV
FLASK_ENV=$(echo "$FLASK_ENV" | xargs)

echo "Current FLASK_ENV: '$FLASK_ENV'"

if [ "$FLASK_ENV" = "dev" ]; then
    echo "Setting up SSH tunnel for dev environment"
    
    # Establish SSH tunnel using the SSH private key
    ssh -i vps_key -o StrictHostKeyChecking=no -L 3307:127.0.0.1:3306 root@srv469975.hstgr.cloud -N &
    SSH_PID=$!
    trap "kill $SSH_PID 2>/dev/null" EXIT
    
    echo "Waiting for tunnel to establish..."
    for i in {1..10}; do
        if netstat -tlnp | grep -q 3307; then
            break
        fi
        sleep 1
    done
    
    if netstat -tlnp | grep -q 3307; then
        echo "SSH tunnel setup complete"
    else
        echo "Error: SSH tunnel failed to establish"
        exit 1
    fi

    # Apply database migrations
    echo "Applying database migrations..."
    flask db upgrade
    if [ $? -ne 0 ]; then
        echo "Error: Database migration failed!"
        exit 1
    fi

    if [ "$1" == "debug" ]; then
        echo "Dev environment ready. Waiting for debugger..."
        wait $SSH_PID
        exit 0
    fi

    echo "Starting Flask app without SSL..."
    exec gunicorn --bind=0.0.0.0:5000 --access-logfile - --error-logfile - "app:create_app()"

else
    # Apply database migrations
    echo "Applying database migrations..."
    flask db upgrade
    if [ $? -ne 0 ]; then
        echo "Error: Database migration failed!"
        exit 1
    fi

    echo "Starting Flask app without SSL..."
    
    # Always use port 5000 internally for both Staging and Production
    exec gunicorn --workers 4 --timeout 30 --bind=0.0.0.0:5000 --access-logfile - --error-logfile - "app:app"
fi
