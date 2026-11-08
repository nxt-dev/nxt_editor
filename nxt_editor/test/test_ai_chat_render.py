"""How the AI Assistant panel shows the chat: blocks, Markdown and code."""
# Builtin
import sys
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt_editor.ai import chat_render
from nxt_editor.dockwidgets.syntax import PythonHighlighter

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
STYLES = PythonHighlighter.styles


def plain(html):
    """The text a user sees for html."""
    doc = QtGui.QTextDocument()
    doc.setHtml(html)
    return doc.toPlainText()


class CodeColors(unittest.TestCase):

    def test_python_is_colored_like_the_code_editor(self):
        out = chat_render.highlight_python(
            'def f(self):\n    # note\n    return "hi"')
        self.assertIn('<span style="color:{}">def</span>'.format(
            STYLES['keyword'][0]), out)
        self.assertIn('color:{};font-style:italic">self<'.format(
            STYLES['self'][0]), out)
        self.assertIn('color:{};font-style:italic"># note<'.format(
            STYLES['comment'][0]), out)
        self.assertIn('color:{}">&quot;hi&quot;<'.format(
            STYLES['string'][0]), out)

    def test_nxt_tokens_stand_out_in_strings(self):
        out = chat_render.highlight_python('x = "a_${side}"')
        self.assertIn('font-weight:bold">${side}<', out)

    def test_the_code_is_all_still_there(self):
        code = ('class A(object):\n    """Doc."""\n    x = [1, 2.5]\n\n'
                '    @property\n    def y(self):\n        return {"k": 1}\n')
        self.assertEqual(code, plain('<pre>{}</pre>'.format(
            chat_render.highlight_python(code))).rstrip('\n') + '\n')

    def test_unfinished_code_is_shown_plain(self):
        out = chat_render.highlight_python('x = """still coming')
        self.assertEqual('x = &quot;&quot;&quot;still coming', out)

    def test_html_in_code_is_not_run(self):
        out = chat_render.highlight_python('x = "<b>no</b>"')
        self.assertNotIn('<b>', out)

    def test_json_is_colored(self):
        out = chat_render.highlight_json('{"a": 1, "b": true}')
        self.assertIn(chat_render.COLORS['json_key'], out)
        self.assertIn(chat_render.COLORS['number'], out)


class MarkdownText(unittest.TestCase):

    def test_inline_formatting(self):
        out = chat_render.inline('**bold** *it* `code` ~~gone~~')
        self.assertIn('<b>bold</b>', out)
        self.assertIn('<i>it</i>', out)
        self.assertIn('code', out)
        self.assertIn(chat_render.COLORS['inline_code'], out)
        self.assertIn('<s>gone</s>', out)

    def test_inline_code_is_left_alone(self):
        out = chat_render.inline('`**not bold**`')
        self.assertNotIn('<b>', out)

    def test_links(self):
        out = chat_render.inline('[docs](https://example.com) and '
                                 'https://nxt.dev/x.')
        self.assertIn('<a href="https://example.com"', out)
        self.assertIn('<a href="https://nxt.dev/x"', out)

    def test_html_in_a_reply_is_shown_not_run(self):
        out = chat_render.markdown('<script>alert(1)</script>')
        self.assertNotIn('<script>', out)
        self.assertIn('&lt;script&gt;', out)

    def test_blocks(self):
        out = chat_render.markdown(
            '# Title\n\n- one\n- two\n\n1. first\n\n> quoted\n\n---\n\n'
            '```python\nx = 1\n```\nafter')
        text = plain(out)
        for piece in ('Title', 'one', 'two', 'first', 'quoted', 'x = 1',
                      'after'):
            self.assertIn(piece, text)
        self.assertIn('<ul', out)
        self.assertIn('<ol', out)
        self.assertIn('<hr>', out)
        self.assertIn(chat_render.COLORS['code_bg'], out)

    def test_a_fence_still_arriving_is_shown_as_code(self):
        out = chat_render.markdown('Here:\n```python\nx = 1')
        self.assertIn(chat_render.COLORS['code_bg'], out)
        self.assertIn('x', plain(out))


class Messages(unittest.TestCase):

    def test_who_said_it_is_shown(self):
        self.assertIn('You', plain(chat_render.user_html('hi')))
        reply = chat_render.reply_html('Claude · opus', 'hello')
        self.assertIn('Claude · opus', plain(reply))
        self.assertNotEqual(chat_render.COLORS['user_bg'],
                            chat_render.COLORS['reply_bg'])

    def test_changes_and_failures_have_their_own_blocks(self):
        out = chat_render.changes_html({'done': ['Made /a'],
                                        'failed': ['There is no node /b']})
        self.assertIn(chat_render.COLORS['done_bg'], out)
        self.assertIn(chat_render.COLORS['failed_bg'], out)
        text = plain(out)
        self.assertIn('Changed the graph', text)
        self.assertIn('Made /a', text)
        self.assertIn('There is no node /b', text)
        self.assertEqual('', chat_render.changes_html({}))


if __name__ == '__main__':
    unittest.main()
