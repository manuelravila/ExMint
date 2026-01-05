#!/bin/bash
set -e
echo "Creating virtual environment in /code/ExMint/venv..."
python3 -m venv /code/ExMint/venv
echo "Virtual environment created."
echo "Upgrading pip..."
/code/ExMint/venv/bin/pip install --upgrade pip
echo "Installing dependencies from /code/ExMint/requirements.txt..."
/code/ExMint/venv/bin/pip install -r /code/ExMint/requirements.txt
echo "Dependencies installed successfully."
