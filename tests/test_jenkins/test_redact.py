import pytest

from mcp_jenkins.jenkins.redact import (
    redact_config_xml,
    redact_parameter_default,
    redact_params,
    redact_text,
)


@pytest.mark.parametrize(
    ('text', 'secret'),
    [
        ('API_TOKEN=&quot;abc123&quot;', 'abc123'),
        ("TOKEN='x1y2z3'", 'x1y2z3'),
        ('PASSWORD = hunter2', 'hunter2'),
        ('password: swordfish', 'swordfish'),
        ('git clone https://user:pw123@github.com/a/b.git', 'pw123'),
        ('curl -u admin:s3cret http://host', 's3cret'),
        ('curl --user admin:s3cret http://host', 's3cret'),
        ('deploy --password hunter http://host', 'hunter'),
        ('Authorization: Bearer abcdefghijkl.mnop', 'abcdefghijkl'),
        ('key {AQAAABAAAAAwq1J1v3m8o2oQwJrEiE0uR0pGq0o9a1f6bW4tZzZ1o9o=}', 'AQAAABAAAAAwq1J1'),
    ],
)
def test_secret_shapes_are_masked(text, secret):
    assert secret not in redact_text(text)
    assert 'REDACTED' in redact_text(text)


@pytest.mark.parametrize(
    'text',
    [
        'export PASS_TOKEN=$FROM_ENV',
        'tokenizer is fine',
        'npm run build:prod',
        'Started by user kirtan.bhavsar',
        'credentialsId deploy-key',
        'x' * 5000,
    ],
)
def test_ordinary_text_is_unchanged(text):
    assert redact_text(text) == text


def test_redaction_is_fast_on_adversarial_input():
    import time

    text = ('a' * 40 + 'token' + 'b' * 40 + ' ') * 400
    start = time.time()
    redact_text(text)

    assert time.time() - start < 1.0


def test_config_keeps_credential_ids_but_hides_secret_elements():
    xml = '<credentialsId>deploy-key</credentialsId><password>p</password><apiToken>t</apiToken>'

    out = redact_config_xml(xml)

    assert '<credentialsId>deploy-key</credentialsId>' in out
    assert '>p<' not in out
    assert '>t<' not in out


class TestParameters:
    def test_password_type_and_secret_named_defaults_are_hidden(self):
        assert redact_parameter_default('hudson.model.PasswordParameterDefinition', 'X', '{AQAAABAA}') == '[REDACTED]'
        assert redact_parameter_default('hudson.model.StringParameterDefinition', 'DEPLOY_TOKEN', 'abc') == '[REDACTED]'

    def test_ordinary_defaults_are_kept(self):
        assert redact_parameter_default('hudson.model.StringParameterDefinition', 'BRANCH', 'main') == 'main'
        assert redact_parameter_default('s', 'BRANCH', None) == ''

    def test_build_parameters(self):
        out = redact_params({'BRANCH': 'main', 'DEPLOY_TOKEN': 'zzz', 'DRY_RUN': True, 'NOTE': 'curl -u a:b http://h'})

        assert out['BRANCH'] == 'main'
        assert out['DEPLOY_TOKEN'] == '[REDACTED]'
        assert out['DRY_RUN'] is True
        assert 'a:b' not in out['NOTE']
