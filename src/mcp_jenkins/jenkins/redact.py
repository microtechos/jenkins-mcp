import re

_REDACTED = '[REDACTED]'

# Redaction is bounded work: anything past this is dropped and replaced by a marker, so malformed or huge input can
# not keep the server busy for long.
_MAX_REDACT_CHARS = 2_000_000
_TRUNCATED = '\n[truncated: too large to redact]'

# Long words match anywhere in a name (dbPassword, MY_SECRET_KEY); short ones only as a whole word delimited by
# anything that is not a letter or digit (DB_PASS, pw, PWD) so "bypass" and "passed" are left alone.
_LONG_WORDS = r'(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|passphrase|storepass|keypass)'  # noqa: S105
_SHORT_WORDS = r'(?<![A-Za-z0-9])(?:pass|pwd|pw)(?![A-Za-z0-9])'
_SECRET_WORDS = r'(?:' + _LONG_WORDS + r'|' + _SHORT_WORDS + r')'

# One possessive run of name characters (no backtracking, so the cost stays linear). Whether it is a secret name is
# decided in code after the match.
_NAME = r'\b(?P<name>[A-Za-z0-9_.-]{1,80}+)'
_QUOTE = r'(?:&quot;|&#39;|&apos;|"|\')'

# Jenkins stores secrets as {base64...}; they must never reach a model even though they are encrypted.
_ENCRYPTED_SECRET = re.compile(r'\{[A-Za-z0-9+/=]{20,}\}')

# <password>x</password>, <apiToken>x</apiToken>, <privateKey>x</privateKey>, ...
_SECRET_ELEMENT = re.compile(
    r'(<(?P<tag>[\w.:-]{0,40}' + _LONG_WORDS + r'[\w.:-]{0,40})(?:\s[^>]{0,100})?>)'
    r'(?P<body>[^<]+)'
    r'(</(?P=tag)>)',
    re.IGNORECASE,
)

# NAME="a value with spaces", "password": "x", password => "x", API_TOKEN=&quot;x&quot;: masked up to the closing quote.
_QUOTED_ASSIGNMENT = re.compile(
    r'(?P<head>' + _NAME + r'(?:' + _QUOTE + r')?\s{0,3}+(?:=>|[=:])\s{0,3}+'
    + _QUOTE
    + r')(?P<value>[^"\'<>&]{1,500})',
)

# NAME=value, NAME: value (no quotes). A $VARIABLE reference or a {...} placeholder is not a secret and is kept.
_ASSIGNMENT = re.compile(
    r'(?P<head>' + _NAME + r'\s{0,3}+(?:=>|[=:])\s{0,3}+)(?![$\{<])(?P<value>[^\s\'"&<>;,)]+)',
)

# Gradle / Groovy style: storePassword "x", keyPassword 'x' (a space, then a quoted value)
_SPACE_QUOTED = re.compile(
    r'(?P<head>' + _NAME + r'[ \t]{1,5}+(?P<q>["\']))(?P<value>[^"\'\r\n]{1,200})(?P=q)',
)

# https://user:password@host and https://TOKEN@host (a token-like userinfo of 20+ characters, no colon)
_URL_USERINFO = re.compile(r'(?P<head>\b[a-z][a-z0-9+.-]{1,15}://[^/\s:@]+:)(?P<pw>[^/\s@]+)(?=@)', re.IGNORECASE)
_URL_TOKEN = re.compile(r'(?P<head>\b[a-z][a-z0-9+.-]{1,15}://)(?P<tok>[A-Za-z0-9_.~-]{20,})(?=@)', re.IGNORECASE)

# curl -u user:password / --user user:password, --password value
_CLI_CREDENTIAL = re.compile(r'(?P<head>(?:\s-u|\s--user)[\s=]+[^\s:]+:)(?P<pw>\S+)')
_CLI_PASSWORD_FLAG = re.compile(r'(?P<head>--(?:password|token|api-key)[\s=]+)(?P<pw>[^\s\'"]+)', re.IGNORECASE)

# keytool -storepass x -keypass x (and the -src/-dest variants)
_KEYTOOL = re.compile(r'(?P<head>\s-(?:src|dest)?(?:store|key)pass\s+)(?P<pw>[^\s\'"]+)', re.IGNORECASE)

# docker login ... -p x, sshpass -p x, mysql -px
_DOCKER_LOGIN = re.compile(r'(?P<head>\bdocker\s+login\b[^\r\n]{0,200}?\s-p[\s=]+)(?P<pw>[^\s\'"]+)', re.IGNORECASE)
_SSHPASS = re.compile(r'(?P<head>\bsshpass\s+(?:-\w+\s+){0,3}?-p\s*)(?P<pw>[^\s\'"]+)', re.IGNORECASE)
_MYSQL = re.compile(r'(?P<head>\bmysql\w*\b[^\r\n]{0,200}?\s-p)(?P<pw>[^\s\'"-][^\s\'"]*)', re.IGNORECASE)

# Authorization: Bearer abc.def / Authorization: Basic YWJjOmRlZg==
_BEARER = re.compile(r'(?P<head>\bBearer\s+)(?P<tok>[A-Za-z0-9._~+/=-]{8,})', re.IGNORECASE)
# The token must look like base64 (an upper-case letter, a digit, + / or =), so a plain word is left alone.
_BASIC = re.compile(
    r'(?P<head>\bAuthorization\s*:\s*Basic\s+)(?P<tok>(?=(?-i:[A-Za-z0-9+/=]*[A-Z0-9+/=]))[A-Za-z0-9+/=]{8,})',
    re.IGNORECASE,
)

_SECRET_NAME = re.compile(_SECRET_WORDS, re.IGNORECASE)
_LONG_SECRET_NAME = re.compile(_LONG_WORDS, re.IGNORECASE)

_VALUE_PATTERNS = (
    _URL_USERINFO,
    _URL_TOKEN,
    _CLI_CREDENTIAL,
    _CLI_PASSWORD_FLAG,
    _KEYTOOL,
    _DOCKER_LOGIN,
    _SSHPASS,
    _MYSQL,
    _BEARER,
    _BASIC,
)


def _bounded(text: str) -> str:
    return text if len(text) <= _MAX_REDACT_CHARS else text[:_MAX_REDACT_CHARS] + _TRUNCATED


def is_secret_name(name: str) -> bool:
    """True when a parameter or variable name looks like it holds a secret."""
    return bool(_SECRET_NAME.search(name or ''))


def _is_long_secret_name(name: str) -> bool:
    return bool(_LONG_SECRET_NAME.search(name or ''))


def _mask(match: re.Match, is_secret: object, *, closing_quote: bool = False) -> str:
    """Replace a matched value when its name is a secret name; otherwise leave the text as it was."""
    if not is_secret(match.group('name')):
        return match.group(0)
    return f'{match.group("head")}{_REDACTED}{match.group("q") if closing_quote else ""}'


def redact_text(text: str) -> str:
    """Mask secret-looking values in free text (console lines, pipeline scripts, parameter values).

    Best effort, not a guarantee. It covers NAME=value / NAME: value assignments (quoted, with spaces, JSON or
    Groovy style, or XML-escaped), URL userinfo, curl -u, keytool and --password style flags, docker login,
    sshpass and mysql passwords, Bearer and Basic authorization, and Jenkins' encrypted {...} secrets.
    Input over 2 MB is cut and marked.
    """
    out = _ENCRYPTED_SECRET.sub('{REDACTED}', _bounded(text))
    for pattern in _VALUE_PATTERNS:
        out = pattern.sub(lambda m: f'{m.group("head")}{_REDACTED}', out)
    out = _QUOTED_ASSIGNMENT.sub(lambda m: _mask(m, is_secret_name), out)
    out = _SPACE_QUOTED.sub(lambda m: _mask(m, _is_long_secret_name, closing_quote=True), out)
    return _ASSIGNMENT.sub(lambda m: _mask(m, is_secret_name), out)


def redact_data(data: object) -> object:
    """Redact every string inside nested dicts and lists; values under secret-named keys are hidden entirely."""
    if isinstance(data, str):
        return redact_text(data)
    if isinstance(data, dict):
        return {
            key: _REDACTED if isinstance(value, str) and is_secret_name(str(key)) else redact_data(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_data(item) for item in data]
    if isinstance(data, tuple):
        return tuple(redact_data(item) for item in data)
    return data


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
    out = _ENCRYPTED_SECRET.sub('{REDACTED}', _bounded(xml))
    out = _SECRET_ELEMENT.sub(lambda m: f'{m.group(1)}{_REDACTED}{m.group(4)}', out)
    return redact_text(out)
