#!/usr/bin/env python3
"""Utility to open the MySQL SSH tunnel used by the ExMint app."""

import argparse
import socket
import subprocess
import sys
import time


TUNNELS = {
    "dev": {
        "local_port": 3307,
        "remote_port": 3306,
        "remote_host": "127.0.0.1",
        "ssh_target": "root@automatos.ca",
    },
    "prod": {
        "local_port": 3308,
        "remote_port": 3306,
        "remote_host": "127.0.0.1",
        "ssh_target": "root@automatos.ca",
    },
}


def is_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if something is listening on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def open_tunnel(config: dict) -> None:
    """Open the SSH tunnel if it is not already established."""
    local_port = config["local_port"]
    remote_port = config["remote_port"]
    remote_host = config["remote_host"]
    ssh_target = config["ssh_target"]

    if is_listening(local_port):
        print(f"Port {local_port} already in use; assuming tunnel is active.")
        return

    command = [
        "ssh",
        "-f",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-L",
        f"{local_port}:{remote_host}:{remote_port}",
        ssh_target,
    ]

    print(
        f"Opening tunnel {local_port}->{remote_host}:{remote_port} via {ssh_target}..."
    )
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to open tunnel: {exc}") from exc

    time.sleep(1.0)
    if not is_listening(local_port):
        raise SystemExit("Tunnel command exited, but port is still closed.")

    print(f"Tunnel ready on localhost:{local_port}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open the SSH tunnel used by the ExMint database."
    )
    parser.add_argument(
        "--env",
        choices=sorted(TUNNELS.keys()),
        default="dev",
        help="Which environment tunnel to open (default: dev).",
    )
    args = parser.parse_args(argv)

    config = TUNNELS[args.env]
    open_tunnel(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
