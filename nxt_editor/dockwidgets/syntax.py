# External
from Qt.QtCore import QRegExp
from Qt.QtGui import QColor, QTextCharFormat, QFont, QSyntaxHighlighter
# Internal
from nxt import tokens


class PythonHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for the Python language.
    """
    # Syntax styles that can be shared by all languages
    styles = {
        'keyword':   ('#619ea8', None),
        'operator':  ('red', None),
        'brace':     ('darkGray', None),
        'defclass':  ('#d8d8d8', None),
        'string':    ('#d162d1', None),
        'string2':   ('#79aa63', 'italic'),
        'comment':   ('#909090', 'italic'),
        'decorator': ('#6bd13d', None),
        'todo':      ('#d9aa00', None),
        'self':      ('#ff00e9', 'italic'),
        'STAGE':     ('#429ed8', 'italic'),
        '${}':       ('#CC7832', 'bold'),
        'numbers':   ('brown', None)
    }

    # Python keywords
    keywords = [
        'and', 'as', 'assert', 'break', 'class', 'continue', 'def', 'del',
        'elif', 'else', 'except', 'exec', 'finally', 'for', 'from', 'global',
        'if', 'import', 'in', 'is', 'lambda', 'not', 'or', 'pass', 'print',
        'raise', 'return', 'try', 'while', 'yield', 'None', 'True', 'False'
    ]

    # Python operators
    operators = [
        '=',
        # Comparison
        '==', '!=', '<', '<=', '>', '>=',
        # Arithmetic
        r'\+', '-', r'\*', '/', '//', r'\%', r'\*\*',
        # In-place
        r'\+=', '-=', r'\*=', '/=', r'\%=',
        # Bitwise
        r'\^', r'\|', r'\&', r'\~', '>>', '<<'
    ]

    # Python braces
    braces = [r'\{', r'\}', r'\(', r'\)', r'\[', r'\]']

    # Block states, carried from one line to the next by Qt. A line that
    # ends inside a triple quoted string hands its state to the next one.
    STATE_NORMAL = 0
    STATE_TRIPLE_SINGLE = 1
    STATE_TRIPLE_DOUBLE = 2

    def __init__(self, document=None):
        super(PythonHighlighter, self).__init__(document)

        rules = []

        # Keyword, operator, and brace rules
        rules += [(r'\b%s\b' % w, 0, self.lookup('keyword')) for w in PythonHighlighter.keywords]
        rules += [(r'%s' % o, 0, self.lookup('operator')) for o in PythonHighlighter.operators]
        rules += [(r'%s' % b, 0, self.lookup('brace')) for b in PythonHighlighter.braces]

        # All other rules
        rules += [
            # 'STAGE'
            (r'\bSTAGE\b', 0, self.lookup('STAGE')),
            # 'self'
            (r'\bself\b', 0, self.lookup('self')),
            (r'\b__init__\b', 0, self.lookup('self')),

            # Decorator
            (r'\@\w*', 0, self.lookup('decorator')),

            # 'def' followed by an identifier
            (r'\bdef\b\s*(\w+)', 1, self.lookup('defclass')),
            # 'class' followed by an identifier
            (r'\bclass\b\s*(\w+)', 1, self.lookup('defclass')),

            # Numeric literals
            (r'\b[+-]?[0-9]+[lL]?\b', 0, self.lookup('numbers')),
            (r'\b[+-]?0[xX][0-9A-Fa-f]+[lL]?\b', 0, self.lookup('numbers')),
            (r'\b[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b', 0, self.lookup('numbers')),
        ]
        # Strings and comments are not found with regex rules. Whether a
        # quote or a # starts one depends on everything to its left, so
        # they are found by walking the line instead, see
        # string_comment_spans.
        self.span_formats = {
            'string': self.lookup('string'),
            'string2': self.lookup('string2'),
            'comment': self.lookup('comment'),
        }
        # From 'todo' until the end of the comment it is in
        self.todo_rule = (QRegExp(r'(todo|Todo)[^\n]*'), 0,
                          self.lookup('todo'))

        # Build a QRegExp for each pattern
        special_rules = [
            # tokens.TOKEN_PREFIX
            (r'\$\{[\w\./:\$\{]*\}', 0, self.lookup('${}')),
            (r'(?<=\$\{)(\})', 0, self.lookup('${}'))
        ]
        self.rules = []
        for (pat, index, fmt) in rules:
            self.rules.append((QRegExp(pat), index, fmt))
        # Rules that need more than regex to work. They run last, so a
        # token inside a string or a comment still shows as a token.
        self.special_rules = []
        for (pat, index, fmt) in special_rules:
            self.special_rules.append((QRegExp(pat), index, fmt))

    def apply_rule(self, text, expression, nth, formatting, special=False,
                   start=0, end=None):
        """Format every match of one rule on the line.

        :param special: True for the token rules, see below
        :param start: only matches that start at or after this column
        :param end: only matches that start before this column, and they
            are cut off there
        """
        end = len(text) if end is None else end
        # Iterate every match on the line, not just the first one. Matching
        # starts at start, so a match that began earlier cannot swallow one
        # inside the range.
        iterator = expression.globalMatch(text, start)
        while iterator.hasNext():
            match = iterator.next()
            # We actually want the index of the nth match
            index = match.capturedStart(nth)
            if index < start or index >= end:
                continue
            captured = match.captured(nth)
            # A nested token (${...${...}}) needs one extra char
            # highlighted, because you can't do nested logic in regex.
            # Decided per match: a line with two tokens side by side is
            # not nested, and would colour the char after each one.
            extra = 0
            if special and captured.count(tokens.TOKEN_PREFIX) > 1:
                extra = 1
            length = min(len(captured) + extra, end - index)
            self.setFormat(index, length, formatting)

    def highlightBlock(self, text):
        """Apply syntax highlighting to the given block of text.
        """
        # Code first, so strings and comments paint over anything the code
        # rules found inside them: a keyword in a string is just text.
        for expression, nth, formatting in self.rules:
            self.apply_rule(text, expression, nth, formatting)

        previous = self.previousBlockState()
        if previous < 0:
            # The first line, or one Qt has not highlighted yet
            previous = self.STATE_NORMAL
        spans, state = string_comment_spans(text, previous)
        for start, length, kind in spans:
            self.setFormat(start, length, self.span_formats[kind])
            if kind == 'comment':
                self.apply_rule(text, *self.todo_rule, start=start,
                                end=start + length)
        self.setCurrentBlockState(state)

        for expression, nth, formatting in self.special_rules:
            self.apply_rule(text, expression, nth, formatting, special=True)

    def lookup(self, key):
        """Return a QTextCharFormat with the given attributes.
        """
        color, style = self.styles[key]

        _color = QColor()
        _color.setNamedColor(color)

        _format = QTextCharFormat()
        _format.setForeground(_color)
        if style:
            if 'bold' in style:
                _format.setFontWeight(QFont.Bold)
            if 'italic' in style:
                _format.setFontItalic(True)

        return _format


def string_comment_spans(text, state=PythonHighlighter.STATE_NORMAL):
    """Find the strings and the comment on one line of Python.

    Walks the line left to right, so a # inside a string is part of the
    string and a quote inside a comment is part of the comment. A triple
    quoted string can run on past the end of the line, which the returned
    state says, and the next line is walked starting from that state.

    :param text: one line, without its newline
    :type text: str
    :param state: the state the line before ended in
    :type state: int
    :return: ([(start, length, kind), ...], state at the end of the line),
        where kind is 'string', 'string2' (triple quoted) or 'comment'
    :rtype: tuple
    """
    triple_quotes = {PythonHighlighter.STATE_TRIPLE_SINGLE: "'''",
                     PythonHighlighter.STATE_TRIPLE_DOUBLE: '"""'}
    spans = []
    length = len(text)
    i = 0
    if state in triple_quotes:
        close = find_closing_quote(text, 0, triple_quotes[state])
        if close < 0:
            # The whole line is still inside the string
            spans.append((0, length, 'string2'))
            return spans, state
        spans.append((0, close, 'string2'))
        i = close
    state = PythonHighlighter.STATE_NORMAL
    while i < length:
        char = text[i]
        if char == '#':
            spans.append((i, length - i, 'comment'))
            break
        if char not in ('"', "'"):
            i += 1
            continue
        if text.startswith(char * 3, i):
            close = find_closing_quote(text, i + 3, char * 3)
            if close < 0:
                # Runs on to the next line
                spans.append((i, length - i, 'string2'))
                if char == "'":
                    state = PythonHighlighter.STATE_TRIPLE_SINGLE
                else:
                    state = PythonHighlighter.STATE_TRIPLE_DOUBLE
                break
            spans.append((i, close - i, 'string2'))
            i = close
            continue
        close = find_closing_quote(text, i + 1, char)
        # One left open is a string to the end of the line, which is how
        # it reads while it is being typed.
        close = length if close < 0 else close
        spans.append((i, close - i, 'string'))
        i = close
    return spans, state


def find_closing_quote(text, start, quote):
    """Where a string that ends with ``quote`` stops, skipping escapes.

    :param text: the line
    :type text: str
    :param start: the column just inside the opening quote
    :type start: int
    :param quote: the quote that closes it, one or three characters
    :type quote: str
    :return: the column just past the closing quote, or -1 if it is not
        closed on this line
    :rtype: int
    """
    i = start
    length = len(text)
    while i < length:
        if text[i] == '\\':
            i += 2
            continue
        if text.startswith(quote, i):
            return i + len(quote)
        i += 1
    return -1
