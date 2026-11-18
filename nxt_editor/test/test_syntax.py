"""The code editor's Python highlighting: strings, comments and docstrings.

A # inside a string used to be coloured as a comment to the end of the
line, because the comment rule was a regex that ran after the string ones.
"""
# Builtin
import sys
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt_editor.dockwidgets import syntax

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class HighlightTestCase(unittest.TestCase):

    def setUp(self):
        # Highlighted the way the code editor is, as the document of a
        # plain text edit, which is what keeps it up to date while typing.
        self.edit = QtWidgets.QPlainTextEdit()
        self.document = self.edit.document()
        self.highlighter = syntax.PythonHighlighter(self.document)
        self.styles = {key: self.highlighter.lookup(key).foreground().color()
                       for key in syntax.PythonHighlighter.styles}

    def highlight(self, text):
        self.edit.setPlainText(text)

    def kind_at(self, line, column):
        """The style name the character at line, column is drawn with."""
        block = self.document.findBlockByNumber(line)
        color = None
        for fmt_range in block.layout().formats():
            if fmt_range.start <= column < fmt_range.start + fmt_range.length:
                color = fmt_range.format.foreground().color()
        if color is None:
            return None
        for key, style_color in self.styles.items():
            if style_color == color:
                return key
        return 'unknown'

    def column(self, line, needle):
        return self.document.findBlockByNumber(line).text().index(needle)


class TestStringsAndComments(HighlightTestCase):

    def test_hash_in_double_quotes_is_string(self):
        self.highlight('x = "a # b"')
        self.assertEqual('string', self.kind_at(0, self.column(0, '#')))
        self.assertEqual('string', self.kind_at(0, self.column(0, 'b')))

    def test_hash_in_single_quotes_is_string(self):
        self.highlight("x = 'a # b'")
        self.assertEqual('string', self.kind_at(0, self.column(0, '#')))

    def test_code_after_string_with_hash_is_not_comment(self):
        self.highlight('x = "#" + str(1)')
        self.assertEqual('operator', self.kind_at(0, self.column(0, '+')))
        self.assertEqual('numbers', self.kind_at(0, self.column(0, '1')))

    def test_comment_after_string_is_comment(self):
        self.highlight('x = "a" # note "quoted"')
        self.assertEqual('string', self.kind_at(0, self.column(0, 'a')))
        self.assertEqual('comment', self.kind_at(0, self.column(0, '#')))
        self.assertEqual('comment', self.kind_at(0, self.column(0, 'quoted')))

    def test_quote_in_comment_does_not_open_a_string(self):
        self.highlight("# it's here\nx = 1")
        self.assertEqual('comment', self.kind_at(0, self.column(0, 's')))
        self.assertEqual('numbers', self.kind_at(1, self.column(1, '1')))

    def test_escaped_quote_stays_in_string(self):
        self.highlight(r'x = "say \" # hi" + y')
        self.assertEqual('string', self.kind_at(0, self.column(0, '#')))
        self.assertEqual('operator', self.kind_at(0, self.column(0, '+')))

    def test_keyword_in_string_is_string(self):
        self.highlight('x = "if and not"')
        self.assertEqual('string', self.kind_at(0, self.column(0, 'and')))

    def test_token_in_string_is_still_a_token(self):
        self.highlight('x = "${value} # 1"')
        self.assertEqual('${}', self.kind_at(0, self.column(0, '${')))
        self.assertEqual('string', self.kind_at(0, self.column(0, '#')))

    def test_todo_only_in_comments(self):
        self.highlight('todo_list = 1  # todo: more')
        self.assertNotEqual('todo', self.kind_at(0, 0))
        self.assertEqual('todo', self.kind_at(0, self.column(0, 'todo:')))


class TestTripleQuotes(HighlightTestCase):

    def test_docstring_across_lines(self):
        self.highlight('"""Start\n# not a comment\nif x\n"""\nif y: pass')
        self.assertEqual('string2', self.kind_at(0, 0))
        self.assertEqual('string2', self.kind_at(1, 0))
        self.assertEqual('string2', self.kind_at(2, 0))
        self.assertEqual('string2', self.kind_at(3, 0))
        self.assertEqual('keyword', self.kind_at(4, 0))

    def test_single_quote_docstring_across_lines(self):
        self.highlight("x = '''a\n'b' # c\n''' # done")
        self.assertEqual('string2', self.kind_at(1, self.column(1, '#')))
        self.assertEqual('comment', self.kind_at(2, self.column(2, '#')))

    def test_triple_quotes_on_one_line(self):
        self.highlight('"""one # line""" # real\nx = 2')
        self.assertEqual('string2', self.kind_at(0, self.column(0, '#')))
        self.assertEqual('comment', self.kind_at(0, self.column(0, '# real')))
        self.assertEqual('numbers', self.kind_at(1, self.column(1, '2')))

    def test_other_quote_kind_does_not_close(self):
        self.highlight('"""a\n\'\'\' # still\n"""\nz = 3')
        self.assertEqual('string2', self.kind_at(1, self.column(1, '#')))
        self.assertEqual('numbers', self.kind_at(3, self.column(3, '3')))

    def test_editing_open_and_close_updates_following_lines(self):
        self.highlight('a = 1\nb = 2')
        cursor = QtGui.QTextCursor(self.document)
        cursor.insertText('"""\n')
        self.assertEqual('string2', self.kind_at(2, 0))
        cursor.insertText('"""\n')
        self.assertNotEqual('string2', self.kind_at(2, 0))


class TestSpans(unittest.TestCase):

    def test_spans_and_state(self):
        spans, state = syntax.string_comment_spans('a = "#" # c """')
        self.assertEqual([(4, 3, 'string'), (8, 7, 'comment')], spans)
        self.assertEqual(syntax.PythonHighlighter.STATE_NORMAL, state)

    def test_open_triple_quote_carries_state(self):
        spans, state = syntax.string_comment_spans('x = """abc')
        self.assertEqual([(4, 6, 'string2')], spans)
        self.assertEqual(syntax.PythonHighlighter.STATE_TRIPLE_DOUBLE, state)
        spans, state = syntax.string_comment_spans('d""" # e', state)
        self.assertEqual([(0, 4, 'string2'), (5, 3, 'comment')], spans)
        self.assertEqual(syntax.PythonHighlighter.STATE_NORMAL, state)


if __name__ == '__main__':
    unittest.main()
