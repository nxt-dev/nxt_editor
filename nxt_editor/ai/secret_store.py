"""Keep API keys and sign ins in the operating system's own secure store.

Windows Credential Manager, the macOS Keychain, or the Secret Service on
Linux (through secret-tool). All of them are reached with the standard
library, so the editor needs nothing installed in any host. The keyring
package is used if it is installed and none of those are there.

When there is none, or it can not save (a Linux machine with no keyring
set up, often), they go in a file only the user can read instead, the
same way Claude Code and Codex keep theirs.
"""
# Builtin
import binascii
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

# Internal
import nxt_editor
from nxt.constants import USER_DIR

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
                                capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
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
                                capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        if result.returncode or 'error' in result.stderr.lower():
            raise SecretStoreError(result.stderr.strip())

    def delete(self, key):
        result = subprocess.run(['security', 'delete-generic-password',
                                 '-s', SERVICE, '-a', key],
                                capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        if result.returncode not in (0, self.NOT_FOUND):
            raise SecretStoreError(result.stderr.strip())


class _SecretToolBackend(object):
    """The freedesktop Secret Service (GNOME Keyring, KWallet)."""
    name = 'Secret Service'
    max_size = None

    def get(self, key):
        result = subprocess.run(['secret-tool', 'lookup', 'service',
                                 SERVICE, 'account', key],
                                capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
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
                                input=value, capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        if result.returncode:
            raise SecretStoreError(result.stderr.strip() or
                                   'secret-tool failed')

    def delete(self, key):
        subprocess.run(['secret-tool', 'clear', 'service', SERVICE,
                        'account', key], capture_output=True, text=True,
                        encoding='utf-8', errors='replace')


class _FileBackend(object):
    """A file only this user can read, for when there is no keyring."""
    max_size = None

    def __init__(self, path=None):
        self.path = path or os.path.join(USER_DIR, 'ai_sign_ins.json')
        self.name = 'a private file ({})'.format(self.path)

    def _read(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as err:
            raise SecretStoreError('Could not read {}: {}'.format(self.path,
                                                                   err))
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        folder = os.path.dirname(self.path)
        try:
            if not os.path.isdir(folder):
                os.makedirs(folder)
            # Written whole and then swapped in, readable by this user only.
            handle, temp = tempfile.mkstemp(dir=folder, prefix='.ai_sign_ins')
            try:
                os.chmod(temp, 0o600)
                with os.fdopen(handle, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                os.replace(temp, self.path)
            except BaseException:
                try:
                    os.remove(temp)
                except OSError:
                    pass
                raise
        except OSError as err:
            raise SecretStoreError('Could not save to {}: {}'.format(
                self.path, err))

    def get(self, key):
        return self._read().get(key)

    def set(self, key, value):
        data = self._read()
        data[key] = value
        self._write(data)

    def delete(self, key):
        data = self._read()
        if key in data:
            del data[key]
            if data:
                self._write(data)
            else:
                try:
                    os.remove(self.path)
                except OSError:
                    pass


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
    first one says how many there are. When the backend can not save, the
    fallback (a private file) is used, and problem says why.
    """
    _PREFIX = 'nxt-chunks:'

    def __init__(self, backend=None, fallback=None):
        self.backend = backend
        self.fallback = fallback
        # Why the backend could not be used, the last time it was not.
        self.problem = None
        self._used_fallback = False

    @property
    def available(self):
        return self.backend is not None or self.fallback is not None

    @property
    def name(self):
        if self.backend and not self._used_fallback:
            return self.backend.name
        if self.fallback:
            return self.fallback.name
        return self.backend.name if self.backend else None

    def describe(self):
        """Where keys and sign ins are kept, for the settings."""
        if not self.available:
            return None
        if self.backend and self._used_fallback and self.problem:
            return ('{} could not save keys and sign ins ({}), so they are '
                    'kept in {}.'.format(self.backend.name, self.problem,
                                         self.fallback.name))
        if not self.backend and self.fallback:
            return ('There is no keyring on this computer, so keys and sign '
                    'ins are kept in {}.'.format(self.fallback.name))
        return 'Keys and sign ins are kept in {}.'.format(self.name)

    def _require(self):
        if not self.available:
            raise SecretStoreError('There is no secure storage on this '
                                   'computer.')

    @classmethod
    def _get_from(cls, backend, key):
        raw = backend.get(key)
        if raw and raw.startswith(cls._PREFIX):
            count, first = raw[len(cls._PREFIX):].split(':', 1)
            parts = [first]
            for i in range(1, int(count)):
                parts.append(backend.get('{}.{}'.format(key, i)) or '')
            raw = ''.join(parts)
        if not raw:
            return None
        return json.loads(raw)

    def get(self, key):
        """The record saved under key, or None."""
        for backend in (self.backend, self.fallback):
            if not backend:
                continue
            try:
                record = self._get_from(backend, key)
            except (SecretStoreError, ValueError) as err:
                if backend is self.backend and self.fallback:
                    # Said once in the settings rather than on every read.
                    self.problem = str(err)
                    logger.debug('Could not read {} from {}: {}'.format(
                        key, backend.name, err))
                else:
                    logger.warning('Could not read the saved {} sign in '
                                   'from {}: {}'.format(key, backend.name,
                                                        err))
                continue
            if record is not None:
                if backend is self.fallback and self.backend:
                    self._used_fallback = True
                return record
        return None

    @classmethod
    def _set_in(cls, backend, key, raw):
        size = backend.max_size
        if not size or len(raw) <= size:
            backend.set(key, raw)
            return
        parts = [raw[i:i + size] for i in range(0, len(raw), size)]
        for i, part in enumerate(parts[1:], 1):
            backend.set('{}.{}'.format(key, i), part)
        backend.set(key, '{}{}:{}'.format(cls._PREFIX, len(parts),
                                            parts[0]))

    def set(self, key, record):
        self._require()
        self.delete(key)
        raw = json.dumps(record)
        if self.backend:
            try:
                self._set_in(self.backend, key, raw)
                return
            except (SecretStoreError, OSError) as err:
                if not self.fallback:
                    raise SecretStoreError('{} could not save it: {}'.format(
                        self.backend.name, err))
                self.problem = str(err) or type(err).__name__
                self._used_fallback = True
                logger.warning('{} could not save the {} sign in ({}), so it '
                               'is kept in {}.'.format(
                                   self.backend.name, key, self.problem,
                                   self.fallback.name))
        self._set_in(self.fallback, key, raw)

    @classmethod
    def _delete_from(cls, backend, key):
        try:
            raw = backend.get(key)
        except SecretStoreError:
            raw = None
        if raw and raw.startswith(cls._PREFIX):
            count = int(raw[len(cls._PREFIX):].split(':', 1)[0])
            for i in range(1, count):
                backend.delete('{}.{}'.format(key, i))
        backend.delete(key)

    def delete(self, key):
        for backend in (self.backend, self.fallback):
            if not backend:
                continue
            try:
                self._delete_from(backend, key)
            except (SecretStoreError, OSError) as err:
                logger.debug('Could not remove {} from {}: {}'.format(
                    key, backend.name, err))


_store = None


def get_store():
    global _store
    if _store is None:
        _store = SecretStore(_find_backend(), fallback=_FileBackend())
    return _store
