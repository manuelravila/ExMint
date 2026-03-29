# Flask App Dockerfile

# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory
WORKDIR /app

# Install necessary packages for Bitwarden CLI
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    ca-certificates \
    openssh-client \
    sshpass \
    jq \
    net-tools

# Download Bitwarden Secrets Manager CLI binary and install it
RUN wget https://github.com/bitwarden/sdk/releases/download/bws-v0.5.0/bws-x86_64-unknown-linux-gnu-0.5.0.zip \
    && unzip bws-x86_64-unknown-linux-gnu-0.5.0.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/bws \
    && rm bws-x86_64-unknown-linux-gnu-0.5.0.zip

# Copy the current directory contents into the container at /app
COPY . /app

# Set up SSH key for dev DB tunnel — only present in dev environments.
# Stag and prod connect to the database directly (no tunnel needed).
RUN if [ -f /app/dev_docker_key ]; then \
    cp /app/dev_docker_key /root/.ssh/id_rsa && \
    chmod 600 /root/.ssh/id_rsa; \
fi

# Make start.sh executable
COPY start.sh /app/start.sh
RUN chmod 755 /app/start.sh

# Install any needed packages specified in requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable
ENV FLASK_APP=app.py

# Entry point to start the application
RUN ls -l /app/start.sh
ENTRYPOINT ["/bin/sh", "/app/start.sh"]