"""Completion context: what the editor is asking to complete at the cursor.

The context is a plain value object produced by inspecting the text left of
the cursor. It is the single input to the completion model, keeping the model
free of any Qt/editor knowledge.
"""
import re
from enum import Enum

from nxt import tokens

# Trailing identifier left of the cursor (the prefix being typed).
_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*$')


class ContextKind(Enum):
    """The kind of completion the cursor position calls for."""
    NONE = 'none'              # nothing to complete
    CODE = 'code'              # Python code -> jedi / fallback name lists
    TOKEN_NODE = 'token-node'  # inside ${...} before a '.' -> node paths
    TOKEN_ATTR = 'token-attr'  # inside ${path. -> attribute names


class CompletionContext(object):
    """Description of a completion request.

    :param kind: ContextKind for this request.
    :param prefix: The already typed text the candidates must start with.
    :param source: The full editor buffer (jedi needs the whole document).
    :param line: 1-based line of the cursor (jedi convention).
    :param column: 0-based column of the cursor (jedi convention).
    :param token_body: For TOKEN_* kinds, the text inside ${...} up to the
    cursor.
    """

    def __init__(self, kind, prefix='', source='', line=1, column=0,
                 token_body=''):
        self.kind = kind
        self.prefix = prefix
        self.source = source
        self.line = line
        self.column = column
        self.token_body = token_body

    @property
    def is_token(self):
        return self.kind in (ContextKind.TOKEN_NODE, ContextKind.TOKEN_ATTR)

    def __repr__(self):
        return ('CompletionContext(kind={!r}, prefix={!r}, line={}, column={})'
                .format(self.kind.value, self.prefix, self.line, self.column))


def detect(source, line, column, jedi_enabled=True):
    """Build a CompletionContext from buffer text and a cursor position.

    :param source: Full editor text.
    :param line: 1-based cursor line.
    :param column: 0-based cursor column.
    :param jedi_enabled: When False an empty code prefix yields NONE (the
    static fallback can't usefully complete a bare '.').
    :return: CompletionContext
    """
    lines = source.split('\n')
    current = lines[line - 1] if 0 <= line - 1 < len(lines) else ''
    left = current[:column]

    # ${...} token context wins over Python code.
    token_start = left.rfind(tokens.TOKEN_PREFIX)
    in_token = (token_start != -1 and
                tokens.TOKEN_SUFFIX not in left[token_start:])
    if in_token:
        body = left[token_start + len(tokens.TOKEN_PREFIX):]
        if '.' in body:
            attr_prefix = body.rpartition('.')[2]
            return CompletionContext(ContextKind.TOKEN_ATTR, prefix=attr_prefix,
                                     source=source, line=line, column=column,
                                     token_body=body)
        return CompletionContext(ContextKind.TOKEN_NODE, prefix=body,
                                 source=source, line=line, column=column,
                                 token_body=body)

    # Python code context.
    match = _IDENT_RE.search(left)
    prefix = match.group(0) if match else ''
    if not prefix:
        # Empty prefix only completes attribute access right after a '.'.
        if jedi_enabled and left.endswith('.'):
            return CompletionContext(ContextKind.CODE, prefix='', source=source,
                                     line=line, column=column)
        return CompletionContext(ContextKind.NONE)
    return CompletionContext(ContextKind.CODE, prefix=prefix, source=source,
                             line=line, column=column)
