#!/bin/bash

# Trim any leading or trailing whitespace from FLASK_ENV
FLASK_ENV=$(echo "$FLASK_ENV" | xargs)

echo "Current FLASK_ENV: '$FLASK_ENV'"

# Create catalog folder and remove old manifests
mkdir -p /app/dist/catalog
rm -f /app/dist/catalog/manifest*.xml

# Use the correct directory for copying the manifest files
if [ "$FLASK_ENV" = "stag" ]; then
    echo "Using staging manifest file"
    cp /app/dist/manifest-stag.xml /app/dist/manifest.xml
    cp /app/dist/manifest-stag.xml /app/dist/catalog/manifest.xml

elif [ "$FLASK_ENV" = "main" ]; then
    echo "Using production manifest file"
    cp /app/dist/manifest-prod.xml /app/dist/manifest.xml
    cp /app/dist/manifest-prod.xml /app/dist/catalog/manifest.xml
fi

# Start the http-server to serve the application
http-server . -p 3000
