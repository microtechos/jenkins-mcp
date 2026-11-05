import re

_REDACTED = '[REDACTED]'

_SECRET_WORDS = r'(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|passphrase)'  # noqa: S105

# Jenkins stores secrets as {base64...}; they must never reach a model even though they are encrypted.
_ENCRYPTED_SECRET = re.compile(r'\{[A-Za-z0-9+/=]{20,}\}')

# <password>x</password>, <apiToken>x</apiToken>, <privateKey>x</privateKey>, ...
_SECRET_ELEMENT = re.compile(
    r'(<(?P<tag>[\w.:-]{0,40}' + _SECRET_WORDS + r'[\w.:-]{0,40})(?:\s[^>]*)?>)'
    r'(?P<body>[^<]+)'
    r'(</(?P=tag)>)',
    re.IGNORECASE,
)

# NAME=value, NAME = "value", NAME: value, TOKEN='x' and the XML-escaped forms (&quot; / &#39;). A $VARIABLE
# reference or a {...} placeholder is not a secret and is kept.
_SECRET_ASSIGNMENT = re.compile(
    r'(?P<head>\b[A-Za-z0-9_.-]{0,40}' + _SECRET_WORDS + r'[A-Za-z0-9_.-]{0,40}\s{0,3}[=:]\s{0,3}'
    r'(?:&quot;|&#39;|&apos;|"|\')?)'
    r'(?![$\{<])(?P<value>[^\s\'"&<>;,)]+)',
    re.IGNORECASE,
)

# https://user:password@host
_URL_USERINFO = re.compile(r'(?P<head>\b[a-z][a-z0-9+.-]{1,15}://[^/\s:@]+:)(?P<pw>[^/\s@]+)(?=@)', re.IGNORECASE)

# curl -u user:password / --user user:password, --password value
_CLI_CREDENTIAL = re.compile(r'(?P<head>(?:\s-u|\s--user)[\s=]+[^\s:]+:)(?P<pw>\S+)')
_CLI_PASSWORD_FLAG = re.compile(r'(?P<head>--(?:password|token|api-key)[\s=]+)(?P<pw>[^\s\'"]+)', re.IGNORECASE)

# Authorization: Bearer abc.def
_BEARER = re.compile(r'(?P<head>\bBearer\s+)(?P<tok>[A-Za-z0-9._~+/=-]{8,})', re.IGNORECASE)

_SECRET_NAME = re.compile(_SECRET_WORDS, re.IGNORECASE)


def is_secret_name(name: str) -> bool:
    """True when a parameter or variable name looks like it holds a secret."""
    return bool(_SECRET_NAME.search(name or ''))


def redact_text(text: str) -> str:
    """Mask secret-looking values in free text (console lines, pipeline scripts, parameter values).

    Best effort, not a guarantee. It covers NAME=value / NAME: value assignments (quoted or XML-escaped),
    URL userinfo, curl -u, --password style flags, Bearer tokens and Jenkins' encrypted {...} secrets.
    """
    out = _ENCRYPTED_SECRET.sub('{REDACTED}', text)
    out = _URL_USERINFO.sub(lambda m: f'{m.group("head")}{_REDACTED}', out)
    out = _CLI_CREDENTIAL.sub(lambda m: f'{m.group("head")}{_REDACTED}', out)
    out = _CLI_PASSWORD_FLAG.sub(lambda m: f'{m.group("head")}{_REDACTED}', out)
    out = _BEARER.sub(lambda m: f'{m.group("head")}{_REDACTED}', out)
    return _SECRET_ASSIGNMENT.sub(lambda m: f'{m.group("head")}{_REDACTED}', out)


def redact_parameter_default(tag: str, name: str, value: str | None) -> str:
    """A job parameter's default value: hidden for password-type or secret-named parameters, else redacted text."""
    if value is None or value == '':
        return ''
    if 'password' in (tag or '').lower() or is_secret_name(name):
        return _REDACTED
    return redact_text(value)


def redact_params(params: dict) -> dict:
    """A build's parameter values: secret-named parameters and encrypted values are hidden, the rest redacted."""
    out = {}
    for key, value in params.items():
        if is_secret_name(str(key)):
            out[key] = _REDACTED
        elif isinstance(value, str):
            out[key] = _REDACTED if _ENCRYPTED_SECRET.search(value) else redact_text(value)
        else:
            out[key] = value
    return out


def redact_config_xml(xml: str) -> str:
    """Mask secret-looking values in a Jenkins config.xml before it is returned to a client.

    Best effort, not a guarantee: it removes the shapes Jenkins itself produces plus obvious inline
    assignments. Credential ids (credentialsId) are not secrets and are left alone.
    """
    out = _ENCRYPTED_SECRET.sub('{REDACTED}', xml)
    out = _SECRET_ELEMENT.sub(lambda m: f'{m.group(1)}{_REDACTED}{m.group(4)}', out)
    return redact_text(out)
