import re

_REDACTED = '[REDACTED]'

# Jenkins stores secrets as {base64...}; they must never reach a model even though they are encrypted.
_ENCRYPTED_SECRET = re.compile(r'\{[A-Za-z0-9+/=]{20,}\}')

# <password>x</password>, <apiToken>x</apiToken>, <privateKey>x</privateKey>, ...
_SECRET_ELEMENT = re.compile(
    r'(<(?P<tag>[\w.:-]*(?:password|passwd|secret|token|apikey|privatekey|passphrase)[\w.:-]*)(?:\s[^>]*)?>)'
    r'(?P<body>[^<]+)'
    r'(</(?P=tag)>)',
    re.IGNORECASE,
)

# Inline shell assignments such as MY_TOKEN=abc123 (a $VARIABLE reference is not a secret and is kept).
_SECRET_ASSIGNMENT = re.compile(
    r'(?P<name>\b[A-Za-z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY)[A-Za-z0-9_]*)=(?!\$)(?P<value>[^\s\'"&<]+)',
    re.IGNORECASE,
)


def redact_config_xml(xml: str) -> str:
    """Mask secret-looking values in a Jenkins config.xml before it is returned to a client.

    Best effort, not a guarantee: it removes the shapes Jenkins itself produces plus obvious inline
    assignments. Credential ids (credentialsId) are not secrets and are left alone.
    """
    out = _ENCRYPTED_SECRET.sub('{REDACTED}', xml)
    out = _SECRET_ELEMENT.sub(lambda m: f'{m.group(1)}{_REDACTED}{m.group(4)}', out)
    return _SECRET_ASSIGNMENT.sub(lambda m: f'{m.group("name")}={_REDACTED}', out)
