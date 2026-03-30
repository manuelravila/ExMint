#!/bin/bash
<<<<<<< HEAD
export PYTHONUNBUFFERED=1

# Use the venv Python directly — avoids relying on the venv activation script
# or the flask/gunicorn entry-point scripts having execute permission.
PYTHON=/code/ExMint/venv/bin/python
GUNICORN=/code/ExMint/venv/bin/gunicorn

=======
source /code/ExMint/venv/bin/activate
export PYTHONUNBUFFERED=1

>>>>>>> de3f4c7c2a9f9894c9802d2a88d7a698e2ff8f6e

# Trim any leading or trailing whitespace from FLASK_ENV
FLASK_ENV=$(echo "$FLASK_ENV" | xargs)

echo "Current FLASK_ENV: '$FLASK_ENV'"

if [ "$FLASK_ENV" = "dev" ]; then
    echo "Setting up SSH tunnel for dev environment"
<<<<<<< HEAD
    $PYTHON open_db_tunnel.py --env dev || exit 1

    # Apply database migrations
    echo "Applying database migrations..."
    $PYTHON -m flask db upgrade
=======
    python open_db_tunnel.py --env dev || exit 1

    # Apply database migrations
    echo "Applying database migrations..."
    flask db upgrade
>>>>>>> de3f4c7c2a9f9894c9802d2a88d7a698e2ff8f6e
    if [ $? -ne 0 ]; then
        echo "Error: Database migration failed!"
        exit 1
    fi

    if [ "$1" == "debug" ]; then
        echo "Dev environment ready. Waiting for debugger..."
        exit 0
    fi

    echo "Starting Flask app without SSL..."
<<<<<<< HEAD
    exec $GUNICORN --bind=0.0.0.0:5000 --access-logfile - --error-logfile - "app:create_app()"
=======
    exec gunicorn --bind=0.0.0.0:5000 --access-logfile - --error-logfile - "app:create_app()"
>>>>>>> de3f4c7c2a9f9894c9802d2a88d7a698e2ff8f6e

else
    # Apply database migrations
    echo "Applying database migrations..."
<<<<<<< HEAD
    $PYTHON -m flask db upgrade
=======
    flask db upgrade
>>>>>>> de3f4c7c2a9f9894c9802d2a88d7a698e2ff8f6e
    if [ $? -ne 0 ]; then
        echo "Error: Database migration failed!"
        exit 1
    fi

    echo "Starting Flask app without SSL..."
    
    # Always use port 5000 internally for both Staging and Production
<<<<<<< HEAD
    exec $GUNICORN --workers 4 --timeout 30 --bind=0.0.0.0:5000 --access-logfile - --error-logfile - "app:app"
=======
    exec gunicorn --workers 4 --timeout 30 --bind=0.0.0.0:5000 --access-logfile - --error-logfile - "app:app"
>>>>>>> de3f4c7c2a9f9894c9802d2a88d7a698e2ff8f6e
fi
