"""Keep API keys and sign ins in the operating system's own secure store.

Windows Credential Manager, the macOS Keychain, or the Secret Service on
Linux (through secret-tool). All of them are reached with the standard
library, so the editor needs nothing installed in any host. The keyring
package is used if it is installed and none of those are there.
"""
# Builtin
import binascii
import json
import logging
import shutil
import subprocess
import sys

# Internal
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

SERVICE = 'nxt_editor'


class SecretStoreError(Exception):
    pass


class _WindowsBackend(object):
    """Windows Credential Manager, through advapi32."""
    name = 'Windows Credential Manager'
    # A generic credential holds at most 2560 bytes, so longer values are
    # split over several.
    max_size = 2048

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [('dwLowDateTime', wintypes.DWORD),
                        ('dwHighDateTime', wintypes.DWORD)]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD),
                        ('Type', wintypes.DWORD),
                        ('TargetName', wintypes.LPWSTR),
                        ('Comment', wintypes.LPWSTR),
                        ('LastWritten', FILETIME),
                        ('CredentialBlobSize', wintypes.DWORD),
                        ('CredentialBlob', ctypes.POINTER(ctypes.c_char)),
                        ('Persist', wintypes.DWORD),
                        ('AttributeCount', wintypes.DWORD),
                        ('Attributes', ctypes.c_void_p),
                        ('TargetAlias', wintypes.LPWSTR),
                        ('UserName', wintypes.LPWSTR)]

        self.CREDENTIAL = CREDENTIAL
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        self._write = advapi32.CredWriteW
        self._write.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        self._write.restype = wintypes.BOOL
        self._read = advapi32.CredReadW
        self._read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                               wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        self._read.restype = wintypes.BOOL
        self._delete = advapi32.CredDeleteW
        self._delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                 wintypes.DWORD]
        self._delete.restype = wintypes.BOOL
        self._free = advapi32.CredFree
        self._free.argtypes = [ctypes.c_void_p]

    GENERIC = 1
    PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    @staticmethod
    def _target(key):
        return '{}:{}'.format(SERVICE, key)

    def get(self, key):
        ctypes = self.ctypes
        found = ctypes.POINTER(self.CREDENTIAL)()
        if not self._read(self._target(key), self.GENERIC, 0,
                          ctypes.byref(found)):
            error = ctypes.get_last_error()
            if error == self.ERROR_NOT_FOUND:
                return None
            raise SecretStoreError('Could not read {} ({})'.format(key,
                                                                    error))
        try:
            cred = found.contents
            data = ctypes.string_at(cred.CredentialBlob,
                                    cred.CredentialBlobSize)
        finally:
            self._free(found)
        return data.decode('utf-8')

    def set(self, key, value):
        ctypes = self.ctypes
        data = value.encode('utf-8')
        blob = ctypes.create_string_buffer(data, len(data))
        cred = self.CREDENTIAL()
        cred.Type = self.GENERIC
        cred.TargetName = self._target(key)
        cred.UserName = SERVICE
        cred.CredentialBlobSize = len(data)
        cred.CredentialBlob = ctypes.cast(blob,
                                          ctypes.POINTER(ctypes.c_char))
        cred.Persist = self.PERSIST_LOCAL_MACHINE
        if not self._write(ctypes.byref(cred), 0):
            raise SecretStoreError('Could not save {} ({})'.format(
                key, ctypes.get_last_error()))

    def delete(self, key):
        if not self._delete(self._target(key), self.GENERIC, 0):
            error = self.ctypes.get_last_error()
            if error != self.ERROR_NOT_FOUND:
                raise SecretStoreError('Could not remove {} ({})'.format(
                    key, error))


class _MacBackend(object):
    """The login Keychain, through the security command."""
    name = 'macOS Keychain'
    max_size = None
    NOT_FOUND = 44

    def get(self, key):
        result = subprocess.run(['security', 'find-generic-password',
                                 '-s', SERVICE, '-a', key, '-w'],
                                capture_output=True, text=True)
        if result.returncode == self.NOT_FOUND:
            return None
        if result.returncode:
            raise SecretStoreError(result.stderr.strip())
        return result.stdout.rstrip('\n')

    def set(self, key, value):
        # Given on stdin rather than as an argument, so the secret never
        # shows in the process list. Hex keeps it clear of quoting.
        hex_value = binascii.hexlify(value.encode('utf-8')).decode('ascii')
        command = 'add-generic-password -U -s {} -a {} -X {}\n'.format(
            SERVICE, key, hex_value)
        result = subprocess.run(['security', '-i'], input=command,
                                capture_output=True, text=True)
        if result.returncode or 'error' in result.stderr.lower():
            raise SecretStoreError(result.stderr.strip())

    def delete(self, key):
        result = subprocess.run(['security', 'delete-generic-password',
                                 '-s', SERVICE, '-a', key],
                                capture_output=True, text=True)
        if result.returncode not in (0, self.NOT_FOUND):
            raise SecretStoreError(result.stderr.strip())


class _SecretToolBackend(object):
    """The freedesktop Secret Service (GNOME Keyring, KWallet)."""
    name = 'Secret Service'
    max_size = None

    def get(self, key):
        result = subprocess.run(['secret-tool', 'lookup', 'service',
                                 SERVICE, 'account', key],
                                capture_output=True, text=True)
        if result.returncode:
            # secret-tool answers 1 both for missing and for errors.
            if result.stderr.strip():
                raise SecretStoreError(result.stderr.strip())
            return None
        return result.stdout

    def set(self, key, value):
        label = 'nxt editor: {}'.format(key)
        result = subprocess.run(['secret-tool', 'store', '--label', label,
                                 'service', SERVICE, 'account', key],
                                input=value, capture_output=True, text=True)
        if result.returncode:
            raise SecretStoreError(result.stderr.strip())

    def delete(self, key):
        subprocess.run(['secret-tool', 'clear', 'service', SERVICE,
                        'account', key], capture_output=True, text=True)


class _KeyringBackend(object):
    """The keyring package, when it is installed."""
    max_size = None

    def __init__(self, keyring):
        self.keyring = keyring
        self.name = type(keyring.get_keyring()).__name__

    def get(self, key):
        return self.keyring.get_password(SERVICE, key)

    def set(self, key, value):
        self.keyring.set_password(SERVICE, key, value)

    def delete(self, key):
        try:
            self.keyring.delete_password(SERVICE, key)
        except self.keyring.errors.PasswordDeleteError:
            pass


def _find_backend():
    if sys.platform == 'win32':
        try:
            return _WindowsBackend()
        except (OSError, AttributeError) as err:
            logger.debug('No Windows Credential Manager: {}'.format(err))
    elif sys.platform == 'darwin':
        if shutil.which('security'):
            return _MacBackend()
    elif shutil.which('secret-tool'):
        return _SecretToolBackend()
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    if isinstance(keyring.get_keyring(), fail.Keyring):
        return None
    return _KeyringBackend(keyring)


class SecretStore(object):
    """Saves small JSON records under a name.

    Values too long for the backend are split over numbered entries; the
    first one says how many there are.
    """
    _PREFIX = 'nxt-chunks:'

    def __init__(self, backend=None):
        self.backend = backend

    @property
    def available(self):
        return self.backend is not None

    @property
    def name(self):
        return self.backend.name if self.backend else None

    def _require(self):
        if not self.backend:
            raise SecretStoreError('There is no secure storage on this '
                                   'computer.')

    def get(self, key):
        """The record saved under key, or None."""
        if not self.backend:
            return None
        try:
            raw = self.backend.get(key)
            if raw and raw.startswith(self._PREFIX):
                count, first = raw[len(self._PREFIX):].split(':', 1)
                parts = [first]
                for i in range(1, int(count)):
                    parts.append(self.backend.get('{}.{}'.format(key, i))
                                 or '')
                raw = ''.join(parts)
            if not raw:
                return None
            return json.loads(raw)
        except (SecretStoreError, ValueError) as err:
            logger.warning('Could not read the saved {} sign in: {}'.format(
                key, err))
            return None

    def set(self, key, record):
        self._require()
        self.delete(key)
        raw = json.dumps(record)
        size = self.backend.max_size
        if not size or len(raw) <= size:
            self.backend.set(key, raw)
            return
        parts = [raw[i:i + size] for i in range(0, len(raw), size)]
        for i, part in enumerate(parts[1:], 1):
            self.backend.set('{}.{}'.format(key, i), part)
        self.backend.set(key, '{}{}:{}'.format(self._PREFIX, len(parts),
                                                 parts[0]))

    def delete(self, key):
        if not self.backend:
            return
        try:
            raw = self.backend.get(key)
        except SecretStoreError:
            raw = None
        if raw and raw.startswith(self._PREFIX):
            count = int(raw[len(self._PREFIX):].split(':', 1)[0])
            for i in range(1, count):
                self.backend.delete('{}.{}'.format(key, i))
        self.backend.delete(key)


_store = None


def get_store():
    global _store
    if _store is None:
        _store = SecretStore(_find_backend())
    return _store
