"""The AI Assistant's chats, kept so they can be gone back to.

Each chat is a json file in the prefs folder, so it stays on this computer.
A pinned chat stays at the top of the list.
"""
# Builtin
import json
import logging
import os
import time
import uuid

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.constants import PREF_DIR

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

CHATS_DIR = os.path.join(PREF_DIR, 'ai_chats')
TITLE_LENGTH = 60
# What a message keeps, the rest is only for this session.
KEPT = ('role', 'content', 'shown', 'who', 'time', 'note', 'done',
        'failed', 'tools')


def title_for(messages):
    """The chat's name: the start of the first question."""
    for message in messages:
        if message.get('role') == 'user':
            text = ' '.join(message.get('shown',
                                        message.get('content', '')).split())
            if len(text) > TITLE_LENGTH:
                text = text[:TITLE_LENGTH - 3].rstrip() + '...'
            return text or 'Chat'
    return 'Chat'


class ChatStore(object):
    """Saves, lists and deletes chats.

    :param folder: where the chats are kept, or None to keep them in memory
    """

    def __init__(self, folder=CHATS_DIR):
        self.folder = folder
        self.memory = {}

    @staticmethod
    def new_id():
        return '{}_{}'.format(time.strftime('%Y%m%d_%H%M%S'),
                              uuid.uuid4().hex[:8])

    def _path(self, chat_id):
        return os.path.join(self.folder, chat_id + '.json')

    def save(self, chat):
        """Keep `chat`, a dict with an id and its messages."""
        messages = [{k: m[k] for k in KEPT if k in m}
                    for m in chat.get('messages', [])]
        record = {'id': chat['id'],
                  'title': chat.get('title') or title_for(messages),
                  'created': chat.get('created') or time.time(),
                  'updated': time.time(),
                  'pinned': bool(chat.get('pinned')),
                  'messages': messages}
        if 'pinned' not in chat:
            # Saving what was said leaves a pin as it was.
            kept = self.load(chat['id'])
            record['pinned'] = bool(kept and kept.get('pinned'))
        chat.update(created=record['created'], updated=record['updated'],
                    title=record['title'])
        self._write(record)

    def _write(self, record):
        if self.folder is None:
            self.memory[record['id']] = json.loads(json.dumps(record))
            return
        try:
            os.makedirs(self.folder, exist_ok=True)
        except OSError as err:
            logger.warning('Could not keep the chat: {}'.format(err))
            return
        user_dir.write_whole_file(
            self._path(record['id']), 'w',
            lambda fp: json.dump(record, fp, indent=1))

    def load(self, chat_id):
        """The chat with `chat_id`, or None if it is gone."""
        if self.folder is None:
            record = self.memory.get(chat_id)
            return json.loads(json.dumps(record)) if record else None
        try:
            with open(self._path(chat_id), 'r') as fp:
                record = json.load(fp)
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict):
            return None
        record['id'] = chat_id
        record.setdefault('messages', [])
        return record

    def set_pinned(self, chat_id, pinned):
        """Pin a chat to the top of the list, or unpin it."""
        record = self.load(chat_id)
        if record is None:
            return
        record['pinned'] = bool(pinned)
        self._write(record)

    def list(self):
        """Every chat as a dict of its id, title, when it was last used and
        whether it is pinned. Pinned first, then most recent first."""
        found = []
        if self.folder is None:
            records = list(self.memory.values())
        else:
            records = []
            if os.path.isdir(self.folder):
                for name in os.listdir(self.folder):
                    if name.endswith('.json'):
                        record = self.load(name[:-5])
                        if record is not None:
                            records.append(record)
        for record in records:
            found.append({'id': record['id'],
                          'title': (record.get('title') or
                                    title_for(record.get('messages', []))),
                          'updated': record.get('updated', 0),
                          'pinned': bool(record.get('pinned'))})
        found.sort(key=lambda chat: (chat['pinned'], chat['updated']),
                   reverse=True)
        return found

    def delete(self, chat_id):
        if self.folder is None:
            self.memory.pop(chat_id, None)
            return
        try:
            os.remove(self._path(chat_id))
        except OSError:
            pass
