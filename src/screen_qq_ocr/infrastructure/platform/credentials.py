"""Generic Windows Credential Manager entries; secrets never enter JSON or SQLite."""

import ctypes
from ctypes import wintypes


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class Credentials:
    def __init__(self, namespace):
        self.namespace = namespace
        self.api = ctypes.WinDLL("Advapi32", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
        ]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def save(self, name, secret):
        blob = secret.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = CREDENTIALW()
        credential.Type = 1
        credential.TargetName = f"{self.namespace}/{name}"
        credential.UserName = "ScreenQQOCR"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = buffer
        credential.Persist = 2
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise OSError("Windows 凭据存储写入失败，凭据未保存")

    def read(self, name):
        pointer = ctypes.POINTER(CREDENTIALW)()
        if not self.api.CredReadW(f"{self.namespace}/{name}", 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return ""
            raise OSError("Windows 凭据存储读取失败")
        try:
            credential = pointer.contents
            return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize).decode(
                "utf-16-le"
            )
        finally:
            self.api.CredFree(pointer)
