"""Small HTTP helpers on the standard library, so no host needs requests."""
# Builtin
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 60
USER_AGENT = 'nxt-editor'


class WebError(Exception):
    """A request that failed, with the most readable message there is."""
    def __init__(self, message, status=None, code=None):
        super(WebError, self).__init__(message)
        self.status = status
        self.code = code


def _context():
    return ssl.create_default_context()


def _error_from(err):
    body = ''
    try:
        body = err.read().decode('utf-8', 'replace')
    except Exception:
        pass
    message, code = None, None
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        found = data.get('error', data)
        if isinstance(found, dict):
            message = (found.get('message') or
                       found.get('error_description') or
                       found.get('detail'))
            if isinstance(message, (list, dict)):
                message = json.dumps(message)[:300]
            code = found.get('code') or found.get('type')
        elif isinstance(found, str):
            message = data.get('error_description') or found
            code = found
    if not message:
        message = body.strip()[:300] or str(err.reason)
    return WebError('{} ({})'.format(message, err.code), status=err.code,
                    code=code)


def request(url, data=None, headers=None, form=None, method=None,
            timeout=TIMEOUT):
    """Open url and give back the response. data is sent as JSON, form as
    form fields."""
    headers = dict(headers or {})
    headers.setdefault('User-Agent', USER_AGENT)
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method=method)
    try:
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=_context())
    except urllib.error.HTTPError as err:
        raise _error_from(err)
    except urllib.error.URLError as err:
        raise WebError('Could not reach {}: {}'.format(
            urllib.parse.urlparse(url).netloc, err.reason))


def get_json(url, headers=None, **kwargs):
    with request(url, headers=headers, **kwargs) as response:
        return json.loads(response.read().decode('utf-8'))


def post_json(url, data=None, headers=None, form=None, **kwargs):
    with request(url, data=data, headers=headers, form=form,
                 **kwargs) as response:
        return json.loads(response.read().decode('utf-8') or '{}')


def iter_sse(response):
    """Yield (event, data) for each server sent event in response. data is
    the parsed JSON, or the raw text when it is not JSON."""
    event, lines = None, []
    for raw in response:
        line = raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if lines:
                text = '\n'.join(lines)
                try:
                    yield event, json.loads(text)
                except ValueError:
                    yield event, text
            event, lines = None, []
            continue
        if line.startswith(':'):
            continue
        field, _, value = line.partition(':')
        value = value[1:] if value.startswith(' ') else value
        if field == 'event':
            event = value
        elif field == 'data':
            lines.append(value)
    if lines:
        text = '\n'.join(lines)
        try:
            yield event, json.loads(text)
        except ValueError:
            yield event, text
