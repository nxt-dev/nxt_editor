# Built-in
import logging
from collections import namedtuple

logger = logging.getLogger('nxt.tokens')

TOKEN_PREFIX = '${'
TOKEN_SUFFIX = '}'

Token = namedtuple('Token', ['prefix', 'detect', 'resolve'])

plugin_tokens = []


def register_token(prefix, detect, resolve):
    logger.info('Registered token: ' + prefix)
    new_token = Token(prefix, detect, resolve)
    global plugin_tokens
    plugin_tokens += [new_token]
    return new_token


class TOKENTYPE(object):
    # TODO: Make these fully defined tokens, right now we're just using them
    #  to unify how we get token prefixes.
    ATTR = Token('', None, None)
    FILE = Token('file::', None, None)
    FILEPATH = Token('path::', None, None)
    PATH = Token('_nxtpath', None, None)
    CONTENTS = Token('contents::', None, None)
    COLOR = Token('_nxtcolor', None, None)
    # ATTR is at the end because it does not have a prefix
    ALL = (FILE, FILEPATH, PATH, CONTENTS, COLOR, ATTR)


def get_token_content(token_str):
    """Removes token prefix and suffix from given token_str

    :param token_str: string to remove token syntax from
    :type token_str: str
    :return: given token_str with token syntax removed
    :rtype: str
    """
    _, _, no_prefix = token_str.partition(TOKEN_PREFIX)
    content, _, _ = no_prefix.rpartition(TOKEN_SUFFIX)
    return content


def make_token_str(token_content):
    """Build a token around given token_content.
    The opposite of `get_token_content`

    :param token_content: token content to wrap
    :type token_content: str
    :return: token content wrapped in token syntax
    :rtype: str
    """
    return TOKEN_PREFIX + token_content + TOKEN_SUFFIX


def get_standalone_tokens(raw_value, token_types=TOKENTYPE.ALL):
    """Get tokens in the given value that are not nested within another token.
    If none are found, an empty list is returned.
    If the token syntax is malformed(extra starts or ends), return empty list.
    Returns list including outer token syntax

    :param raw_value: value to find standalone tokens in.
    :type raw_value: str
    :param token_types: Optionally a list of specific token types can be
    provided, only standalone tokens that look like those token type(s) will
    be returned.
    :type token_types: list or tuple
    :return: list of standalone tokens, if found.
    :rtype: list
    """
    # Early exit if the raw value is None or not a string like object
    if not raw_value or not isinstance(raw_value, basestring):
        return []
    i = 0
    bounds = []
    starts = 0
    ends = 0
    outer_start_idx = -1
    for char in raw_value:
        # First condition verifies we're not at the end of the string, where
        # it would be impossible to get second prefix character.
        if (i+1 < len(raw_value) and
           char == TOKEN_PREFIX[0] and raw_value[i+1] == TOKEN_PREFIX[1]):
            if starts == 0:
                outer_start_idx = i
            starts += 1
        elif starts and char == TOKEN_SUFFIX:
            ends += 1
        if starts > 0 and starts == ends:
            bounds += [(outer_start_idx, i+1)]
            starts = 0
            ends = 0
            outer_start_idx = -1
        i += 1
    if starts != ends:
        return []
    results = []
    for start, end in bounds:
        skip = True
        token_contents = raw_value[start:end]
        for token_type in token_types:
            prefix = token_type.prefix
            if token_contents.startswith(TOKEN_PREFIX+prefix):
                skip = False
        if skip:
            continue
        results += [token_contents]
    return results


def atomic_token_partition(value):
    """Partition given value on a token that appears resolvable(contains no
    sub tokens). Returns in a tuple: (before_token, token, after_token).
    Returned token includes token syntax. If no tokens are found, returned
    tuple contains None in all values.

    :param value: text to find a token from, and partition
    :type value: str
    :return: before_token, token, after_token
    :rtype: tuple(str, str, str)
    """
    before, sep, after_bef = value.rpartition(TOKEN_PREFIX)
    if not sep:
        return (None, None, None)
    token, sep, after = after_bef.partition(TOKEN_SUFFIX)
    if not sep:
        # msg = 'bad resolve formatting, cannot find closer for {}'
        # msg = msg.format(before + tokens.TOKEN_PREFIX)
        # logger.error(msg)
        return (None, None, None)
    return before, make_token_str(token), after


def get_atomic_tokens(value):
    """Return a list of all tokens that appear ready to resolve.

    :param value: string to find tokens in
    :type value: str
    :return: tokens found
    :rtype: list
    """
    found = []
    prefix, content, suffix = atomic_token_partition(value)
    if not content:
        return found
    found += [content]
    if prefix:
        found += get_atomic_tokens(prefix)
    if suffix:
        found += get_atomic_tokens(suffix)
    found = set(found)
    return found


