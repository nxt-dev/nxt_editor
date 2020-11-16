from nxt.tokens import register_token

PREFIX = 'ex::'


def detect_token_type(value):
    return value.startswith(PREFIX)


def resolve_token(stage, node, value, layer, **kwargs):
    value = stage.resolve(node, value, layer, **kwargs)
    # Reverses given value
    return value[::-1]


register_token(PREFIX, detect_token_type, resolve_token)
