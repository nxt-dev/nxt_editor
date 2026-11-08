"""What the assistant remembers between chats, and the folders it may read.

Memory is a list of short notes, sent at the start of every chat. The user
adds them in Options > AI Assistant > Memory, or asks the assistant to
remember something and it adds the note itself.

Folders work as they do in Claude Code: the assistant asks before it reads
files somewhere new, and the user allows it for the chat, always, or not
at all. Folders always allowed are remembered here with what they are for,
so later chats know they are there and use them. The open graph's folder
can always be read.

Kept in the user prefs, so it stays on this computer.
"""
# Builtin
import os
import time
import uuid

# Internal
from nxt_editor import user_dir

MAX_NOTE = 500


def norm(path):
    """A folder path to compare by, the same however it was typed."""
    path = os.path.normpath(os.path.abspath(os.path.expanduser(
        str(path).strip())))
    return os.path.normcase(path)


def inside(path, folder):
    """True if path is folder or anything in it."""
    path, folder = norm(path), norm(folder)
    if path == folder:
        return True
    return path.startswith(folder.rstrip(os.sep) + os.sep)


class Memory(object):
    """The notes and allowed folders in prefs."""

    def __init__(self, prefs=None):
        self.prefs = prefs if prefs is not None else user_dir.user_prefs

    # Notes
    def notes(self):
        notes = self.prefs.get(user_dir.USER_PREF.AI_MEMORY) or []
        return [n for n in notes if isinstance(n, dict) and n.get('text')]

    def _save_notes(self, notes):
        self.prefs[user_dir.USER_PREF.AI_MEMORY] = notes

    def add(self, text):
        """Remember text. Gives back the note."""
        text = ' '.join(str(text).split())[:MAX_NOTE]
        if not text:
            raise ValueError('A note needs some text')
        notes = self.notes()
        for note in notes:
            if note['text'].lower() == text.lower():
                return note
        note = {'id': uuid.uuid4().hex[:6], 'text': text,
                'time': time.time()}
        self._save_notes(notes + [note])
        return note

    def update(self, note_id, text):
        text = ' '.join(str(text).split())[:MAX_NOTE]
        notes = self.notes()
        for note in notes:
            if note['id'] == note_id:
                if text:
                    note['text'] = text
                else:
                    notes.remove(note)
                self._save_notes(notes)
                return True
        return False

    def remove(self, note_id):
        notes = self.notes()
        kept = [n for n in notes if n['id'] != note_id]
        self._save_notes(kept)
        return len(kept) != len(notes)

    # Folders
    def folders(self):
        folders = self.prefs.get(user_dir.USER_PREF.AI_FOLDERS) or []
        return [f for f in folders if isinstance(f, dict) and f.get('path')]

    def allow(self, path, about=''):
        """Always let the assistant read path. Gives back the entry."""
        path = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
        folders = self.folders()
        for folder in folders:
            if norm(folder['path']) == norm(path):
                if about and not folder.get('about'):
                    folder['about'] = about
                    self.prefs[user_dir.USER_PREF.AI_FOLDERS] = folders
                return folder
        folder = {'path': path, 'about': ' '.join(str(about).split()),
                  'time': time.time()}
        self.prefs[user_dir.USER_PREF.AI_FOLDERS] = folders + [folder]
        return folder

    def set_about(self, path, about):
        folders = self.folders()
        for folder in folders:
            if norm(folder['path']) == norm(path):
                folder['about'] = ' '.join(str(about).split())
                self.prefs[user_dir.USER_PREF.AI_FOLDERS] = folders
                return True
        return False

    def disallow(self, path):
        folders = self.folders()
        kept = [f for f in folders if norm(f['path']) != norm(path)]
        self.prefs[user_dir.USER_PREF.AI_FOLDERS] = kept
        return len(kept) != len(folders)

    def allowed(self, path):
        return any(inside(path, f['path']) for f in self.folders())

    # What the assistant is told
    def describe(self):
        lines = []
        notes = self.notes()
        if notes:
            lines.append('What you have been asked to remember (forget a '
                         'note with forget and its id when it is wrong):')
            for note in notes:
                lines.append('- [{}] {}'.format(note['id'], note['text']))
        folders = self.folders()
        if folders:
            if lines:
                lines.append('')
            lines.append('Folders the user has let you read. Look in them '
                         'when a question touches what they hold:')
            for folder in folders:
                about = folder.get('about')
                lines.append('- {}{}'.format(
                    folder['path'], ': ' + about if about else ''))
        return '\n'.join(lines)
