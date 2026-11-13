"""Turn the chat into HTML for the AI Assistant panel.

Each message gets its own colored block, labeled with who wrote it and when,
with the day shown wherever it changes, as chat apps do. Replies
are Markdown: headings, lists, quotes, links, bold, italics and inline code
are shown as such, and fenced code is colored the way the code editor
colors it. Plain Python only, so nothing is needed in any host.
"""
# Builtin
import datetime
import html
import io
import keyword
import re
import token
import tokenize

# Internal
from nxt_editor import theme
from nxt_editor.dockwidgets.syntax import PythonHighlighter

STYLES = PythonHighlighter.styles
MONO = "Consolas, 'DejaVu Sans Mono', Menlo, monospace"

COLORS = {
    'user_bg': '#2c3a4c',
    'user_name': '#8fb8ff',
    'reply_bg': theme.RAISED,
    'reply_name': '#e3a35f',
    'code_bg': '#1a1a1a',
    'code_label': '#7a7a7a',
    'inline_code_bg': theme.HOVER,
    'inline_code': '#e6c07b',
    'link': '#6fb3ff',
    'quote': '#a0a0a0',
    'heading': theme.TEXT,
    'done_bg': '#1f3324',
    'done_name': '#7fd18b',
    'failed_bg': '#3a2222',
    'failed_name': '#ff8a80',
    'note': '#c9b26d',
    'number': '#d19a66',
    'json_key': '#8fb8ff',
    'time': '#8a8a8a',
    'activity': '#a8a8a8',
    'read': '#6fb3ff',
    'show': '#c79bdb',
    'edit': '#7fd18b',
    'run': '#e3a35f',
    'memory': '#e8c96b',
}
# Steps shown in a reply before the earlier ones are counted instead.
MOST_STEPS = 8


def _style(name):
    color, extra = STYLES.get(name, (None, None))
    css = []
    if color:
        css.append('color:{}'.format(color))
    if extra == 'italic':
        css.append('font-style:italic')
    elif extra == 'bold':
        css.append('font-weight:bold')
    return ';'.join(css)


def _span(text, css):
    text = html.escape(text)
    return '<span style="{}">{}</span>'.format(css, text) if css else text


_NXT_TOKEN = re.compile(r'(\$\{[^}]*\})')


def _string_html(text, css):
    """A string, with nxt's ${attr} tokens picked out as the editor does."""
    parts = []
    for i, piece in enumerate(_NXT_TOKEN.split(text)):
        parts.append(_span(piece, _style('${}') if i % 2 else css))
    return ''.join(parts)


def highlight_python(code):
    """Python as HTML, colored like the code editor. Code that does not
    tokenize is shown plain."""
    out = []
    lines = code.split('\n')
    # Offsets of each line start, to cut the source between tokens.
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)

    def offset(row_col):
        row, col = row_col
        return starts[row - 1] + col
    last = 0
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return html.escape(code)
    for tok in tokens:
        if tok.type in (token.ENDMARKER,):
            continue
        start, end = offset(tok.start), offset(tok.end)
        if start < last:
            continue
        out.append(html.escape(code[last:start]))
        text = code[start:end]
        css = ''
        if tok.type == token.COMMENT:
            css = _style('todo') if 'TODO' in text else _style('comment')
        elif tok.type == token.STRING:
            triple = text.lstrip('rbuRBUfF')[:3] in ('"""', "'''")
            out.append(_string_html(text, _style('string2' if triple
                                                 else 'string')))
            last = end
            continue
        elif tok.type == token.NUMBER:
            css = 'color:{}'.format(COLORS['number'])
        elif tok.type == token.NAME:
            if text in ('self', '__init__'):
                css = _style('self')
            elif text == 'STAGE':
                css = _style('STAGE')
            elif keyword.iskeyword(text) or text == 'print':
                css = _style('keyword')
        elif tok.type == token.OP:
            if text in '()[]{}':
                css = _style('brace')
            elif text == '@':
                css = _style('decorator')
            else:
                css = _style('operator')
        out.append(_span(text, css))
        last = end
    out.append(html.escape(code[last:]))
    return ''.join(out)


_JSON = re.compile(r'("(?:[^"\\]|\\.)*")(\s*:)?|(-?\b\d+(?:\.\d+)?\b)|'
                   r'\b(true|false|null)\b')


def highlight_json(code):
    out, last = [], 0
    for match in _JSON.finditer(code):
        out.append(html.escape(code[last:match.start()]))
        string, colon, number, word = match.groups()
        if string is not None:
            color = COLORS['json_key'] if colon else STYLES['string'][0]
            out.append(_span(string, 'color:{}'.format(color)))
            if colon:
                out.append(html.escape(colon))
        elif number is not None:
            out.append(_span(number, 'color:{}'.format(COLORS['number'])))
        else:
            out.append(_span(word, _style('keyword')))
        last = match.end()
    out.append(html.escape(code[last:]))
    return ''.join(out)


def code_block(code, language=''):
    language = (language or '').strip().lower()
    if language in ('python', 'py', ''):
        body = highlight_python(code)
        label = 'python' if language else ''
    elif language in ('json', 'nxt', 'nxt-actions'):
        body = highlight_json(code)
        label = language
    else:
        body = html.escape(code)
        label = language
    head = ''
    if label:
        head = ('<div style="color:{}; font-size:small">{}</div>'.format(
            COLORS['code_label'], html.escape(label)))
    return ('<table width="100%" cellpadding="8" cellspacing="0" '
            'style="background-color:{bg}; margin-top:4px; '
            'margin-bottom:4px"><tr><td>{head}<pre style="font-family:{mono};'
            ' margin:0">{body}</pre></td></tr></table>').format(
                bg=COLORS['code_bg'], head=head, mono=MONO, body=body)


# Markdown
_INLINE_CODE = re.compile(r'`([^`\n]+)`')
_LINK = re.compile(r'\[([^\]\n]+)\]\((https?://[^)\s]+)\)')
_URL = re.compile(r'(?<!["=>])\b(https?://[^\s<]+[^\s<.,;:!?)\]])')
_BOLD = re.compile(r'\*\*(.+?)\*\*|__(.+?)__')
_ITALIC = re.compile(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|'
                     r'(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])')
_STRIKE = re.compile(r'~~(.+?)~~')


def inline(text):
    """One line of Markdown as HTML."""
    kept = []

    def keep(snippet):
        kept.append(snippet)
        return '\x00{}\x00'.format(len(kept) - 1)

    text = _INLINE_CODE.sub(lambda m: keep(
        '<span style="font-family:{}; background-color:{}; color:{}">'
        '&nbsp;{}&nbsp;</span>'.format(MONO, COLORS['inline_code_bg'],
                                       COLORS['inline_code'],
                                       html.escape(m.group(1)))), text)
    text = _LINK.sub(lambda m: keep('<a href="{}" style="color:{}">{}</a>'
                                    .format(html.escape(m.group(2)),
                                            COLORS['link'],
                                            html.escape(m.group(1)))), text)
    text = _URL.sub(lambda m: keep('<a href="{0}" style="color:{1}">{0}</a>'
                                   .format(html.escape(m.group(1)),
                                           COLORS['link'])), text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(lambda m: '<b>{}</b>'.format(m.group(1) or m.group(2)),
                     text)
    text = _ITALIC.sub(lambda m: '<i>{}</i>'.format(m.group(1) or
                                                     m.group(2)), text)
    text = _STRIKE.sub(r'<s>\1</s>', text)
    return re.sub('\x00(\\d+)\x00', lambda m: kept[int(m.group(1))], text)


_FENCE = re.compile(r'^\s*```\s*([\w.+-]*)\s*$')
_HEADING = re.compile(r'^(#{1,6})\s+(.*)$')
_BULLET = re.compile(r'^(\s*)[-*+]\s+(.*)$')
_NUMBERED = re.compile(r'^(\s*)\d+[.)]\s+(.*)$')
_RULE = re.compile(r'^\s*([-*_])(\s*\1){2,}\s*$')
_SIZES = {1: 'x-large', 2: 'large', 3: 'medium', 4: 'medium', 5: 'small',
          6: 'small'}


def markdown(text):
    """Markdown as HTML, for the parts of it a chat reply uses."""
    out = []
    lines = (text or '').split('\n')
    i = 0
    paragraph = []
    list_kind = None

    def end_paragraph():
        if paragraph:
            out.append('<p style="margin-top:2px; margin-bottom:6px">{}</p>'
                       .format('<br>'.join(inline(l) for l in paragraph)))
            del paragraph[:]

    def end_list():
        if list_kind:
            out.append('</{}>'.format(list_kind))
        return None

    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            end_paragraph()
            list_kind = end_list()
            language = fence.group(1)
            code = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            # An open fence is code still arriving.
            out.append(code_block('\n'.join(code), language))
            i += 1
            continue
        if not line.strip():
            end_paragraph()
            list_kind = end_list()
            i += 1
            continue
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        numbered = _NUMBERED.match(line)
        if heading:
            end_paragraph()
            list_kind = end_list()
            level = len(heading.group(1))
            out.append('<p style="font-size:{}; font-weight:bold; color:{}; '
                       'margin-top:6px; margin-bottom:4px">{}</p>'.format(
                           _SIZES[level], COLORS['heading'],
                           inline(heading.group(2))))
        elif _RULE.match(line):
            end_paragraph()
            list_kind = end_list()
            out.append('<hr>')
        elif bullet or numbered:
            end_paragraph()
            kind = 'ul' if bullet else 'ol'
            if list_kind != kind:
                list_kind = end_list()
                out.append('<{} style="margin-top:2px; margin-bottom:4px">'
                           .format(kind))
                list_kind = kind
            out.append('<li>{}</li>'.format(
                inline((bullet or numbered).group(2))))
        elif line.lstrip().startswith('>'):
            end_paragraph()
            list_kind = end_list()
            out.append('<p style="color:{}; font-style:italic; '
                       'margin-left:12px">{}</p>'.format(
                           COLORS['quote'],
                           inline(line.lstrip()[1:].strip())))
        else:
            if list_kind:
                list_kind = end_list()
            paragraph.append(line)
        i += 1
    end_paragraph()
    end_list()
    return ''.join(out)


def clock(when):
    """The time of day of `when` (seconds since the epoch), as 3:42 PM."""
    stamp = datetime.datetime.fromtimestamp(when)
    return '{}:{:02d} {}'.format(stamp.hour % 12 or 12, stamp.minute,
                                 'AM' if stamp.hour < 12 else 'PM')


def day_name(when, now=None):
    """Today, Yesterday, or the date, with the year if it is not this one."""
    day = datetime.datetime.fromtimestamp(when).date()
    today = (now or datetime.datetime.now()).date()
    if day == today:
        return 'Today'
    if day == today - datetime.timedelta(days=1):
        return 'Yesterday'
    text = '{}, {} {}'.format(day.strftime('%A'), day.strftime('%B'),
                              day.day)
    if day.year != today.year:
        text += ', {}'.format(day.year)
    return text


def short_when(when, now=None):
    """When a chat was last used, short enough for the list of chats."""
    day = datetime.datetime.fromtimestamp(when).date()
    today = (now or datetime.datetime.now()).date()
    if day == today:
        return clock(when)
    if day == today - datetime.timedelta(days=1):
        return 'Yesterday'
    if today - day < datetime.timedelta(days=7):
        return day.strftime('%A')
    text = '{} {}'.format(day.strftime('%b'), day.day)
    if day.year != today.year:
        text += ', {}'.format(day.year)
    return text


def day_html(when):
    """The line between messages where the day changes."""
    return ('<p align="center" style="color:{}; font-size:small; '
            'margin:4px 0 8px 0">{}</p>').format(COLORS['time'],
                                                  html.escape(day_name(when)))


def _block(name, name_color, background, body, when=None):
    stamp = ''
    if when:
        stamp = ('&nbsp;&nbsp;<span style="color:{}; font-weight:normal">'
                 '{}</span>').format(COLORS['time'], clock(when))
    return ('<table width="100%" cellpadding="8" cellspacing="0" '
            'style="background-color:{}; margin-bottom:8px"><tr><td>'
            '<div style="color:{}; font-weight:bold; font-size:small">{}{}'
            '</div>{}</td></tr></table>').format(background, name_color,
                                                 html.escape(name), stamp,
                                                 body)


def changes_html(message):
    """What a reply changed in the graph, and what it could not."""
    parts = []
    if message.get('note'):
        parts.append('<p style="color:{}; font-style:italic">{}</p>'.format(
            COLORS['note'], inline(message['note'])))
    done = message.get('done') or []
    failed = message.get('failed') or []
    if done:
        items = ''.join('<li>{}</li>'.format(inline(d)) for d in done)
        parts.append(_block('Changed the graph (Ctrl+Z undoes it all)',
                            COLORS['done_name'], COLORS['done_bg'],
                            '<ul style="margin:0">{}</ul>'.format(items)))
    if failed:
        items = ''.join('<li>{}</li>'.format(inline(f)) for f in failed)
        parts.append(_block('Could not', COLORS['failed_name'],
                            COLORS['failed_bg'],
                            '<ul style="margin:0">{}</ul>'.format(items)))
    return ''.join(parts)


def user_html(text, when=None):
    return _block('You', COLORS['user_name'], COLORS['user_bg'],
                  markdown(text), when)


def activity_html(steps):
    """What the assistant did with its tools: a line for each step, with a
    dot colored by what kind of step it was."""
    if not steps:
        return ''
    rows = []
    hidden = len(steps) - MOST_STEPS
    if hidden > 0:
        rows.append(('', COLORS['time'], '{} earlier step{}'.format(
            hidden, '' if hidden == 1 else 's'), ''))
        steps = steps[-MOST_STEPS:]
    for step in steps:
        state = step.get('state')
        label = step.get('label') or step.get('name') or ''
        color = COLORS.get(step.get('kind'), COLORS['read'])
        if state == 'running':
            rows.append(('○', color, label + '...', ''))
        elif state == 'failed':
            rows.append(('✕', COLORS['failed_name'], label,
                         step.get('detail') or ''))
        elif state == 'note':
            rows.append(('•', COLORS['note'], label, ''))
        else:
            rows.append(('●', color, label, ''))
    html_rows = []
    for mark, color, label, detail in rows:
        if detail:
            label = '{} <span style="color:{}">— {}</span>'.format(
                html.escape(label), COLORS['failed_name'],
                html.escape(detail[:200]))
        else:
            label = html.escape(label)
        html_rows.append(
            '<tr><td width="14" style="color:{}">{}</td>'
            '<td style="color:{}">{}</td></tr>'.format(
                color, mark, COLORS['activity'], label))
    return ('<table cellpadding="1" cellspacing="0" style="font-size:small; '
            'margin-bottom:6px">{}</table>').format(''.join(html_rows))


def reply_html(name, text, changes='', when=None, activity=None):
    return _block(name, COLORS['reply_name'], COLORS['reply_bg'],
                  activity_html(activity) + markdown(text) + changes, when)


def thinking_html(name):
    """The reply before anything of it has come."""
    return _block(name, COLORS['reply_name'], COLORS['reply_bg'],
                  '<p style="color:{}; font-style:italic">Thinking...'
                  '</p>'.format(COLORS['time']))
