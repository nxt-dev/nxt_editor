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
        '\+', '-', '\*', '/', '//', '\%', '\*\*',
        # In-place
        '\+=', '-=', '\*=', '/=', '\%=',
        # Bitwise
        '\^', '\|', '\&', '\~', '>>', '<<'
    ]

    # Python braces
    braces = ['\{', '\}', '\(', '\)', '\[', '\]']

    def __init__(self, document=None):
        super(PythonHighlighter, self).__init__(document)

        # Multi-line strings (expression, flag, style)
        # FIXME: The triple-quotes in these two lines will mess up the
        # syntax highlighting from this point onward
        self.tri_single = (QRegExp("'''"), 1, self.lookup('string2'))
        self.tri_double = (QRegExp('"""'), 2, self.lookup('string2'))

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

            # Double-quoted string, possibly containing escape sequences
            (r'"[^"\\]*(\\.[^"\\]*)*"', 0, self.lookup('string')),
            # Single-quoted string, possibly containing escape sequences
            (r"'[^'\\]*(\\.[^'\\]*)*'", 0, self.lookup('string')),
            # Decorator
            (r'\@\w*', 0, self.lookup('decorator')),

            # 'def' followed by an identifier
            (r'\bdef\b\s*(\w+)', 1, self.lookup('defclass')),
            # 'class' followed by an identifier
            (r'\bclass\b\s*(\w+)', 1, self.lookup('defclass')),

            # From '#' until a newline
            (r'#[^\n]*', 0, self.lookup('comment')),
            # from 'todo' until a new line
            (r'(todo|Todo)[^\n]*', 0, self.lookup('todo')),

            # Numeric literals
            (r'\b[+-]?[0-9]+[lL]?\b', 0, self.lookup('numbers')),
            (r'\b[+-]?0[xX][0-9A-Fa-f]+[lL]?\b', 0, self.lookup('numbers')),
            (r'\b[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b', 0, self.lookup('numbers')),
        ]

        # Build a QRegExp for each pattern
        special_rules = [
            # tokens.TOKEN_PREFIX
            (r'\$\{[\w\./:\$\{]*\}', 0, self.lookup('${}')),
            (r'(?<=\$\{)(\})', 0, self.lookup('${}'))
        ]
        self.rules = []
        for (pat, index, fmt) in rules:
            self.rules.append((QRegExp(pat), index, fmt))
        # Rules that need more than regex to work
        self.special_rules = []
        for (pat, index, fmt) in special_rules:
            self.rules.append((QRegExp(pat), index, fmt))
            self.special_rules.append((QRegExp(pat), index, fmt))

    def highlightBlock(self, text):
        """Apply syntax highlighting to the given block of text.
        """
        # Do other syntax formatting
        for rule in self.rules:
            expression, nth, formatting = rule
            index = expression.indexIn(text, 0)
            # This is here because you can't do nested logic in regex
            nested = 0
            if rule in self.special_rules:
                if text.count(tokens.TOKEN_PREFIX) > 1:
                    nested = 1

            while index >= 0:
                # We actually want the index of the nth match
                index = expression.pos(nth)
                length = len(expression.cap(nth))
                self.setFormat(index, length + nested, formatting)
                index = expression.indexIn(text, index + length)

        self.setCurrentBlockState(0)

        # Do multi-line strings
        in_multiline = self.match_multiline(text, *self.tri_single)
        if not in_multiline:
            in_multiline = self.match_multiline(text, *self.tri_double)

    def match_multiline(self, text, delimiter, in_state, style):
        """Do highlighting of multi-line strings. ``delimiter`` should be a
        ``QRegExp`` for triple-single-quotes or triple-double-quotes, and
        ``in_state`` should be a unique integer to represent the corresponding
        state changes when inside those strings. Returns True if we're still
        inside a multi-line string when this function is finished.
        """
        # If inside triple-single quotes, start at 0
        if self.previousBlockState() == in_state:
            start = 0
            add = 0
        # Otherwise, look for the delimiter on this line
        else:
            start = delimiter.indexIn(text)
            # Move past this match
            add = delimiter.matchedLength()

        # As long as there's a delimiter match on this line...
        while start >= 0:
            # Look for the ending delimiter
            end = delimiter.indexIn(text, start + add)
            # Ending delimiter on this line?
            if end >= add:
                length = end - start + add + delimiter.matchedLength()
                self.setCurrentBlockState(0)
            # No; multi-line string
            else:
                self.setCurrentBlockState(in_state)
                length = len(text) - start + add
            # Apply formatting
            self.setFormat(start, length, style)
            # Look for the next match
            start = delimiter.indexIn(text, start + length)

        # Return True if still inside a multi-line string, False otherwise
        if self.currentBlockState() == in_state:
            return True
        else:
            return False

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
