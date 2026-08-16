from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


@dataclass(frozen=True)
class OkxCredentials:
    api_key: str
    secret_key: str
    passphrase: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _vault_path() -> Path:
    override = os.environ.get("QH_OKX_VAULT_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise RuntimeError("Windows local application data directory is unavailable")
    return Path(local_app_data) / "QuantHub" / "secrets" / "okx-demo.bin"


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _protect(plaintext: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("The local credential vault requires Windows DPAPI")
    source, source_buffer = _blob(plaintext)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_bool
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "QuantHub OKX Demo", None, None, None, 0, ctypes.byref(output)
    ):
        raise OSError("Windows DPAPI encryption failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def _unprotect(ciphertext: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("The local credential vault requires Windows DPAPI")
    source, source_buffer = _blob(ciphertext)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_bool
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise OSError("Windows DPAPI decryption failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def _restrict_windows_acl(path: Path) -> None:
    if os.name != "nt":
        return
    identity_result = subprocess.run(
        ["whoami"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    identity = identity_result.stdout.strip()
    if identity_result.returncode != 0 or not identity:
        raise OSError("Windows user identity is unavailable for credential ACL")
    completed = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{identity}:(F)",
            "*S-1-5-18:(F)",
        ],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise OSError("Windows credential ACL could not be restricted")


def _read_payload() -> dict[str, Any] | None:
    path = _vault_path()
    if not path.is_file():
        return None
    try:
        encrypted = base64.b64decode(path.read_bytes(), validate=True)
        payload = json.loads(_unprotect(encrypted).decode("utf-8"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The local OKX credential vault cannot be read") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(field), str) and payload[field]
        for field in ("api_key", "secret_key", "passphrase")
    ):
        raise RuntimeError("The local OKX credential vault is invalid")
    return payload


def _write_payload(payload: dict[str, Any]) -> None:
    path = _vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    encrypted = base64.b64encode(_protect(plaintext))
    fd, temporary_name = tempfile.mkstemp(prefix=".okx-demo-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
        _restrict_windows_acl(path)
    finally:
        temporary.unlink(missing_ok=True)


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _runtime_identity() -> str | None:
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["whoami"],
            check=False,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    identity = completed.stdout.strip()
    return identity or None


def _status_base() -> dict[str, Any]:
    return {
        "environment": "demo",
        "source": "local_vault",
        "protection_scope": "windows_current_user",
        "runtime_identity": _runtime_identity(),
    }


def inspect_okx_demo_credentials() -> dict[str, Any]:
    """Return a non-throwing vault status so the UI can offer recovery actions."""
    path = _vault_path()
    try:
        return okx_demo_credential_status()
    except (OSError, RuntimeError):
        return {
            **_status_base(),
            "ok": False,
            "available": False,
            "configured": path.is_file(),
            "fingerprint": None,
            "updated_at": None,
            "validated_at": None,
            "error_code": "credential_vault_unavailable",
            "error": "本机凭据无法由当前 API 运行账户解密",
            "recovery_action": "请使用同一 Windows 用户重启 API，或重新填写并重建凭据",
        }


def save_okx_demo_credentials(credentials: OkxCredentials) -> dict[str, Any]:
    try:
        previous = _read_payload()
    except (OSError, RuntimeError):
        # A corrupt or differently encrypted file must not permanently lock the user
        # out of replacing it. The atomic write and ACL step still fail closed when
        # the current Windows account has no permission to replace the file.
        previous = None
    now = _now()
    _write_payload(
        {
            "version": 1,
            "api_key": credentials.api_key,
            "secret_key": credentials.secret_key,
            "passphrase": credentials.passphrase,
            "created_at": previous.get("created_at", now) if previous else now,
            "updated_at": now,
            "validated_at": None,
        }
    )
    return okx_demo_credential_status()


def load_okx_demo_credentials() -> OkxCredentials:
    payload = _read_payload()
    if payload is None:
        raise RuntimeError("OKX Demo credentials are not configured")
    return OkxCredentials(payload["api_key"], payload["secret_key"], payload["passphrase"])


def okx_demo_credential_status() -> dict[str, Any]:
    payload = _read_payload()
    if payload is None:
        return {
            **_status_base(),
            "ok": True,
            "available": True,
            "configured": False,
            "fingerprint": None,
            "updated_at": None,
            "validated_at": None,
            "error_code": None,
            "error": None,
            "recovery_action": None,
        }
    return {
        **_status_base(),
        "ok": True,
        "available": True,
        "configured": True,
        "fingerprint": _fingerprint(payload["api_key"]),
        "updated_at": payload.get("updated_at"),
        "validated_at": payload.get("validated_at"),
        "error_code": None,
        "error": None,
        "recovery_action": None,
    }


def update_okx_demo_validation(validated_at: str | None = None) -> dict[str, Any]:
    payload = _read_payload()
    if payload is None:
        raise RuntimeError("OKX Demo credentials are not configured")
    payload["validated_at"] = validated_at or _now()
    _write_payload(payload)
    return okx_demo_credential_status()


def delete_okx_demo_credentials() -> dict[str, Any]:
    _vault_path().unlink(missing_ok=True)
    return okx_demo_credential_status()
