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


def _tunnel_healthy(port: int, host: str = "127.0.0.1", timeout: float = 3.0) -> bool:
    """Return True only when the tunnel is forwarding all the way to MySQL.

    MySQL sends a greeting packet immediately on connect, so we know the full
    path (local-port → SSH → remote MySQL) is working when we receive at least
    one byte.  A bare TCP connect (connect_ex == 0) is *not* sufficient: the
    SSH process can have its listen socket open while the tunnel to the remote
    host is broken, which would make the previous is_listening() check pass
    even though every subsequent DB connection would hang.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            # MySQL sends ≥1 byte (its greeting packet) right away.
            return len(sock.recv(1)) > 0
    except (OSError, socket.timeout):
        return False


def _wait_for_tunnel(port: int, host: str = "127.0.0.1",
                     deadline: float = 15.0, interval: float = 0.5) -> bool:
    """Poll until the tunnel is healthy or *deadline* seconds have elapsed."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if _tunnel_healthy(port, host):
            return True
        time.sleep(interval)
    return False


def open_tunnel(config: dict) -> None:
    """Open the SSH tunnel if it is not already established and healthy."""
    local_port = config["local_port"]
    remote_port = config["remote_port"]
    remote_host = config["remote_host"]
    ssh_target = config["ssh_target"]

    if _tunnel_healthy(local_port):
        print(f"Tunnel on port {local_port} is already active and healthy.")
        return

    command = [
        "ssh",
        "-f",
        "-N",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "StrictHostKeyChecking=accept-new",
        "-L", f"{local_port}:{remote_host}:{remote_port}",
        ssh_target,
    ]

    print(
        f"Opening tunnel {local_port}->{remote_host}:{remote_port} via {ssh_target}..."
    )
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to open tunnel: {exc}") from exc

    if not _wait_for_tunnel(local_port):
        raise SystemExit(
            f"Tunnel command exited but port {local_port} did not become "
            "healthy within 15 seconds (no MySQL greeting received)."
        )

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
