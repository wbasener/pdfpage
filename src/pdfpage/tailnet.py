"""Making the local server reachable from your other devices through Tailscale.

Tailscale is a private network between your own machines. `tailscale serve` takes requests that
arrive over that network and passes them to a program listening on the loopback address, so the
machine's firewall is never involved and nothing is opened to the local network or the internet.
Without Tailscale, pdfpage falls back to a plain http://127.0.0.1 address that works on this
machine only.
"""

from __future__ import annotations

import json
import subprocess

from . import store


def _tailscale(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tailscale", *args], capture_output=True, text=True, check=True)


def dns_name() -> str | None:
    """This machine's name on the tailnet, for example dl.example.ts.net, or None."""
    try:
        status = json.loads(_tailscale("status", "--json").stdout)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    name = str(status.get("Self", {}).get("DNSName", "")).rstrip(".")
    return name or None


def publish_path() -> bool:
    """Point the tailnet address at the local server. True if Tailscale accepted it.

    This is set once and stays set; later documents appear under the same path.
    """
    try:
        _tailscale("serve", "--bg", f"--set-path={store.PREFIX}",
                   f"http://127.0.0.1:{store.PORT}{store.PREFIX}")  # fmt: skip
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def unpublish_path() -> bool:
    """Remove the tailnet path. The documents stay on disk."""
    try:
        _tailscale("serve", "--bg", f"--set-path={store.PREFIX}", "off")
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def base_url() -> str:
    """The address documents are published under: the tailnet one if it is available."""
    name = dns_name()
    if name and publish_path():
        return f"https://{name}{store.PREFIX}"
    return f"http://127.0.0.1:{store.PORT}{store.PREFIX}"
