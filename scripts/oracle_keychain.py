"""Small macOS Keychain adapter for the local Oracle preview.

Only the OS Keychain persists credentials. Calls use native framework APIs;
secrets never become command arguments, log messages, or ordinary files.
The caller must validate a replacement with ElevenLabs before saving it.
"""
from __future__ import annotations

import ctypes
import sys


SERVICE = "com.protrader.oracle.preview.elevenlabs"
_NOT_FOUND = -25300
_DUPLICATE = -25299
_MAX_KEY_BYTES = 16384


class KeychainError(RuntimeError):
    """A safe, user-facing Keychain failure, without credential contents."""


def _failure(status: int) -> KeychainError:
    if status == -128:
        return KeychainError("Keychain access was cancelled. The key was not changed.")
    if status in (-25293, -25308):
        return KeychainError("macOS Keychain access was not allowed. Unlock your login Keychain and allow this preview to access its saved key.")
    if status == -25291:
        return KeychainError("macOS Keychain is unavailable. The preview can still use a hidden key for this session.")
    return KeychainError("macOS Keychain could not complete this request. No saved key was deleted.")


class _NativeKeychain:
    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise KeychainError("Secure key storage is available on macOS only. Use the hidden prompt for this session.")
        try:
            self.security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
            self.core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            status = ctypes.c_int32
            uint = ctypes.c_uint32
            pointer = ctypes.c_void_p
            self.security.SecKeychainFindGenericPassword.argtypes = [
                pointer, uint, ctypes.c_char_p, uint, ctypes.c_char_p,
                ctypes.POINTER(uint), ctypes.POINTER(pointer), ctypes.POINTER(pointer),
            ]
            self.security.SecKeychainFindGenericPassword.restype = status
            self.security.SecKeychainAddGenericPassword.argtypes = [
                pointer, uint, ctypes.c_char_p, uint, ctypes.c_char_p,
                uint, pointer, ctypes.POINTER(pointer),
            ]
            self.security.SecKeychainAddGenericPassword.restype = status
            self.security.SecKeychainItemModifyAttributesAndData.argtypes = [pointer, pointer, uint, pointer]
            self.security.SecKeychainItemModifyAttributesAndData.restype = status
            self.security.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
            self.security.SecKeychainItemFreeContent.restype = status
            self.core.CFRelease.argtypes = [pointer]
            self.core.CFRelease.restype = None
        except (OSError, AttributeError):
            raise KeychainError("macOS Keychain support could not be loaded. Use the hidden prompt for this session.") from None


def _identity(agent_id: str) -> tuple[bytes, bytes]:
    try:
        account = agent_id.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise KeychainError("A valid private-agent reference is required for secure key storage.") from None
    if not account or len(account) > 1024 or b"\x00" in account:
        raise KeychainError("A valid private-agent reference is required for secure key storage.")
    return SERVICE.encode("utf-8"), account


def read_key(agent_id: str) -> str | None:
    """Read this agent's saved key; a missing item is the only None result."""
    service, account = _identity(agent_id)
    native = _NativeKeychain()
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    try:
        result = native.security.SecKeychainFindGenericPassword(
            None, len(service), service, len(account), account,
            ctypes.byref(length), ctypes.byref(data), None,
        )
        if result == _NOT_FOUND:
            return None
        if result != 0:
            raise _failure(result)
        if not data.value or not 0 < length.value <= _MAX_KEY_BYTES:
            raise KeychainError("The saved key could not be read. Replace it using the hidden prompt.")
        try:
            return ctypes.string_at(data, length.value).decode("utf-8")
        except UnicodeError:
            raise KeychainError("The saved key could not be read. Replace it using the hidden prompt.") from None
    finally:
        if data.value:
            native.security.SecKeychainItemFreeContent(None, data)


def save_key(agent_id: str, key: str) -> None:
    """Add or update one validated key without deleting the previous item."""
    service, account = _identity(agent_id)
    try:
        encoded = key.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise KeychainError("The key could not be saved. Use the complete secret in the hidden prompt.") from None
    if not encoded or len(encoded) > _MAX_KEY_BYTES or b"\x00" in encoded:
        raise KeychainError("The key could not be saved. Use the complete secret in the hidden prompt.")
    native = _NativeKeychain()
    secret = ctypes.create_string_buffer(encoded)
    length = len(encoded)
    item = ctypes.c_void_p()
    try:
        result = native.security.SecKeychainFindGenericPassword(
            None, len(service), service, len(account), account,
            None, None, ctypes.byref(item),
        )
        if result == _NOT_FOUND:
            result = native.security.SecKeychainAddGenericPassword(
                None, len(service), service, len(account), account,
                length, secret, None,
            )
            # Another launcher may have created the same item meanwhile.
            # Retry the exact identity once, never remove and re-add a key.
            if result != _DUPLICATE:
                if result != 0:
                    raise _failure(result)
                return
            result = native.security.SecKeychainFindGenericPassword(
                None, len(service), service, len(account), account,
                None, None, ctypes.byref(item),
            )
        if result != 0:
            raise _failure(result)
        if not item.value:
            raise KeychainError("macOS Keychain did not return the saved item. The key was not changed.")
        result = native.security.SecKeychainItemModifyAttributesAndData(item, None, length, secret)
        if result != 0:
            raise _failure(result)
    finally:
        ctypes.memset(secret, 0, ctypes.sizeof(secret))
        if item.value:
            native.core.CFRelease(item)
