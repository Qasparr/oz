#!/usr/bin/env python3
"""JOR-EL outer tier — the Tor onion-service front.

This is the "quantum-entanglement" [Coinage: Johnathan "Qasparr (Κασπάρρ)"
Monroe]: the binding between the inner enclave (device-native, loopback
only) and the outer domain (a Tor v3 onion address). The actual mechanism
is plain: a v3 onion service whose private key lives in the hidden-service
directory, with its virtual port mapped to the enclave's loopback socket.
The tor daemon bridges them. No quantum anything — stated plainly.

Key custody is the whole game: whoever holds the hidden-service directory
holds the onion identity (hs_ed25519_secret_key). Guard it like a key,
because it is one.

Honest states:
  - tor binary missing  -> TorNotAvailable (with install guidance)
  - bootstrap timeout   -> TorNotAvailable (Tor network unreachable?)
  - provisioned         -> .onion address; peers address the node by it

Standard library only.
"""
import os
import shutil
import subprocess
import time

TORRC_TEMPLATE = """\
# JOR-EL onion front — generated, do not hand-edit the keys.
DataDirectory {data_dir}
HiddenServiceDir {hs_dir}
HiddenServicePort 80 127.0.0.1:{local_port}
HiddenServiceVersion 3
SocksPort 0
"""


class TorNotAvailable(Exception):
    """Raised when the onion front cannot be provisioned, with the reason."""


def find_tor(tor_bin=None):
    """Return the tor binary path, or raise TorNotAvailable."""
    path = tor_bin or shutil.which("tor")
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise TorNotAvailable(
            "tor binary not found. Install Tor (e.g. `apt-get install tor` "
            "or the Tor Project repository) and retry. The enclave keeps "
            "running on loopback; only the outer domain is missing."
        )
    return path


class OnionFront:
    """Provisions a v3 onion service fronting a loopback enclave port."""

    def __init__(self, service_dir, local_port, tor_bin=None):
        self.service_dir = os.path.abspath(service_dir)
        self.local_port = int(local_port)
        self.tor_bin = tor_bin
        self._proc = None
        self._address = None

    @property
    def address(self):
        return self._address

    def _write_torrc(self):
        data_dir = os.path.join(self.service_dir, "tor-data")
        hs_dir = os.path.join(self.service_dir, "hidden_service")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(hs_dir, exist_ok=True)
        # Tor refuses a group/world-readable hidden-service dir.
        os.chmod(hs_dir, 0o700)
        torrc = os.path.join(self.service_dir, "torrc")
        with open(torrc, "w", encoding="utf-8") as handle:
            handle.write(TORRC_TEMPLATE.format(
                data_dir=data_dir, hs_dir=hs_dir, local_port=self.local_port))
        return torrc, os.path.join(hs_dir, "hostname")

    def provision(self, timeout=180):
        """Launch tor, wait for the onion hostname, return the address.

        Raises TorNotAvailable if tor is missing or bootstrap times out.
        """
        tor = find_tor(self.tor_bin)
        torrc, hostname_file = self._write_torrc()
        self._proc = subprocess.Popen(
            [tor, "-f", torrc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    raise TorNotAvailable(
                        f"tor exited during bootstrap (code {self._proc.returncode}). "
                        "Check the torrc and data directory permissions."
                    )
                if os.path.isfile(hostname_file):
                    with open(hostname_file, encoding="utf-8") as handle:
                        self._address = handle.read().strip()
                    if self._address.endswith(".onion"):
                        return self._address
                time.sleep(2)
        except Exception:
            self.shutdown()
            raise
        self.shutdown()
        raise TorNotAvailable(
            f"onion provisioning timed out after {timeout}s — "
            "is the Tor network reachable from here?"
        )

    def shutdown(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
