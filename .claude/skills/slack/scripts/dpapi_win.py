#!/usr/bin/env python3
"""
Windows DPAPI protect/unprotect via ctypes (pure stdlib, no dependency).

CurrentUser scope: ciphertext can only be decrypted by the same Windows user
account on the same machine. No key material is stored on disk -- the key is
derived from the user's login by the OS. A scheduled task running as that user
can decrypt unattended; a copied file on another machine cannot.
"""
import ctypes
from ctypes import wintypes


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32

# Declare prototypes so pointer args/returns marshal correctly on Win64
# (without argtypes, ctypes defaults to c_int and truncates 64-bit pointers,
# most dangerously the pbData handed to LocalFree).
_PBLOB = ctypes.POINTER(_DATA_BLOB)
_crypt32.CryptProtectData.argtypes = [_PBLOB, wintypes.LPCWSTR, _PBLOB,
                                      ctypes.c_void_p, ctypes.c_void_p,
                                      wintypes.DWORD, _PBLOB]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [_PBLOB, ctypes.POINTER(wintypes.LPWSTR), _PBLOB,
                                        ctypes.c_void_p, ctypes.c_void_p,
                                        wintypes.DWORD, _PBLOB]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p

_CRYPTPROTECT_UI_FORBIDDEN = 0x1  # never show UI; required for unattended use


def _call(fn, data: bytes) -> bytes:
    # Keep `buf` referenced for the whole call: blob_in.pbData points into it,
    # and a GC of buf before fn() runs would be a use-after-free.
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if not fn(ctypes.byref(blob_in), None, None, None, None,
              _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def protect(plaintext: str) -> bytes:
    return _call(_crypt32.CryptProtectData, plaintext.encode("utf-8"))


def unprotect(ciphertext: bytes) -> str:
    return _call(_crypt32.CryptUnprotectData, ciphertext).decode("utf-8")


if __name__ == "__main__":
    secret = "roundtrip-check-value"
    blob = protect(secret)
    assert unprotect(blob) == secret, "DPAPI roundtrip failed"
    assert blob != secret.encode("utf-8"), "ciphertext must differ from plaintext"
    print("ok: DPAPI protect/unprotect roundtrip")
