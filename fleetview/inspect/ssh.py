"""SSH transport for FleetView deep inspection.

Thin wrapper around paramiko.  paramiko is imported *lazily* inside the
constructor so this module (and the rest of ``fleetview.inspect``) imports
cleanly even when the optional ``ssh`` extra is not installed.
"""

from __future__ import annotations

from typing import Optional, Tuple

_PARAMIKO_HINT = (
    "paramiko is required for SSH deep inspection but is not installed. "
    "Install it with:  pip install 'fleetview[ssh]'"
)


class SSHInspector:
    """Run shell commands on a remote guest over SSH.

    Parameters
    ----------
    host:
        Hostname or IP to connect to.
    username:
        SSH login user.
    key_path:
        Optional path to a private key file.
    password:
        Optional password (or key passphrase fallback).
    port:
        TCP port, default 22.
    sudo:
        When True, :meth:`run` prefixes commands with ``sudo -n`` so they run
        non-interactively with elevated privileges.
    timeout:
        Per-operation timeout in seconds.
    """

    def __init__(
        self,
        host: str,
        username: str,
        key_path: Optional[str] = None,
        password: Optional[str] = None,
        port: int = 22,
        sudo: bool = False,
        timeout: int = 15,
    ) -> None:
        try:
            import paramiko  # noqa: F401  (lazy: presence check only)
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(_PARAMIKO_HINT) from exc

        self.host = host
        self.username = username
        self.key_path = key_path
        self.password = password
        self.port = port
        self.sudo = sudo
        self.timeout = timeout
        self._client = None  # type: ignore[assignment]

    def connect(self) -> None:
        """Open the SSH connection if it is not already open."""
        if self._client is not None:
            return
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }
        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        if self.password:
            connect_kwargs["password"] = self.password
        client.connect(**connect_kwargs)
        self._client = client

    def run(self, cmd: str) -> Tuple[str, str, int]:
        """Execute ``cmd`` and return ``(stdout, stderr, exit_code)``.

        When ``sudo=True`` the command is wrapped with ``sudo -n`` so it never
        blocks on a password prompt.
        """
        self.connect()
        assert self._client is not None
        if self.sudo:
            cmd = f"sudo -n {cmd}"
        _stdin, stdout, stderr = self._client.exec_command(cmd, timeout=self.timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err, exit_code

    def close(self) -> None:
        """Close the SSH connection."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "SSHInspector":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
