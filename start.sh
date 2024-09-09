#!/bin/bash

# Trim any leading or trailing whitespace from FLASK_ENV
FLASK_ENV=$(echo "$FLASK_ENV" | xargs)

echo "Current FLASK_ENV: '$FLASK_ENV'"

if [ "$FLASK_ENV" = "dev" ]; then
    echo "Setting up SSH tunnel for dev environment"
    
    # Establish SSH tunnel using the SSH private key
    ssh -i /root/.ssh/id_rsa -o StrictHostKeyChecking=no -L 3307:127.0.0.1:3306 root@srv469975.hstgr.cloud -N &
    
    echo "Waiting for tunnel to establish..."
    sleep 10  # Increase the sleep time to ensure the tunnel is ready
    
    netstat -tlnp | grep 3307
    if [ $? -eq 0 ]; then
        echo "SSH tunnel setup complete"
    else
        echo "Error: SSH tunnel failed to establish"
        exit 1
    fi

    echo "Starting Flask app with SSL..."
    exec gunicorn --certfile=/app/dev_exmint_me.crt --keyfile=/app/dev_exmint_me.key --bind=0.0.0.0:5000 "app:create_app()"

else
    echo "Starting Flask app without SSL..."
    
    # Always use port 5000 internally for both Staging and Production
    exec gunicorn -- workers 4 --timeout 30 --bind=0.0.0.0:5000 "app:app"
fi
