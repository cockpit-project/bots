# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Kerberos → SAML → STS authentication for AWS.

Authenticates via SPNEGO/Negotiate to an IdP, exchanges the SAML assertion
for temporary AWS credentials via STS AssumeRoleWithSAML, and caches
credentials to disk.
"""

import base64
import dataclasses
import fnmatch
import html.parser
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.aws.account import (
    ACCOUNT_ID,
    REDHAT_SSO_IDP_URL,
    REDHAT_SSO_IMAGE_DOWNLOAD_MAX_SESSION,
    REDHAT_SSO_IMAGE_DOWNLOAD_ROLE,
    REDHAT_SSO_SAML_PROVIDER_ARN,
)
from lib.directories import xdg_cache_home
from lib.s3 import S3Key

logger = logging.getLogger(__name__)


# https://docs.aws.amazon.com/STS/latest/APIReference/Welcome.html
_STS_URL = 'https://sts.amazonaws.com/'
_STS_VERSION = '2011-06-15'
_STS_NS = f'https://sts.amazonaws.com/doc/{_STS_VERSION}/'


class AuthError(Exception):
    """Raised when Kerberos/SAML/STS authentication fails."""


def _negotiate_header(idp_url: str) -> str:
    """Create a Negotiate auth header using Kerberos."""
    try:
        import gssapi
        import gssapi.raw.misc
    except ImportError as exc:
        raise AuthError('🐍 no python3-gssapi') from exc

    hostname = urllib.parse.urlparse(idp_url).hostname
    assert hostname is not None
    # fixed in python-gssapi 1.9.0: https://github.com/pythongssapi/python-gssapi/pull/338
    server_name = gssapi.Name(f'HTTP@{hostname}', gssapi.NameType.hostbased_service)  # type: ignore[attr-defined]
    try:
        # fixed in python-gssapi 1.9.0: https://github.com/pythongssapi/python-gssapi/pull/338
        ctx = gssapi.SecurityContext(usage='initiate', name=server_name)  # type: ignore[attr-defined]
        token = base64.b64encode(ctx.step()).decode()
    except gssapi.raw.misc.GSSError as exc:
        statuses = '  '.join(exc.get_all_statuses(exc.min_code, is_maj=False))
        raise AuthError(f'🐕 {statuses}.  Try kinit.') from exc
    logger.debug('obtained SPNEGO token for %r', hostname)
    return f'Negotiate {token}'


def _get_saml_assertion(idp_url: str) -> str:
    """Authenticate via Kerberos and return the base64 SAML assertion."""
    logger.debug('requesting SAML assertion from %r', idp_url)

    request = urllib.request.Request(idp_url)
    request.add_header('Authorization', _negotiate_header(idp_url))
    response = urllib.request.urlopen(request)
    body = response.read().decode()
    logger.debug('IdP response status: %r', response.status)
    logger.debug('IdP response: %d bytes', len(body))

    result: list[str] = []

    class Parser(html.parser.HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            # <input name="SAMLResponse" value="(capture this)">
            if tag == 'input' and ('name', 'SAMLResponse') in attrs:
                result.extend(v for k, v in attrs if v and k == 'value')

    Parser().feed(body)
    if len(result) != 1:
        logger.debug('response body: %r', body[:500])
        raise AuthError('🤔 Failed to find SAMLResponse in IdP response')

    return result[0]


def aws_sts_assume_role(account_id: str, role: str, provider_arn: str, saml_assertion: str, duration: timedelta) -> str:
    """Exchange a SAML assertion for temporary AWS credentials via STS.

    Returns the raw XML response body.
    """
    role_arn = f'arn:aws:iam::{account_id}:role/{role}'
    logger.debug('assuming role %r via STS', role_arn)

    params = urllib.parse.urlencode({
        'Action': 'AssumeRoleWithSAML',
        'Version': _STS_VERSION,
        'RoleArn': role_arn,
        'PrincipalArn': provider_arn,
        'SAMLAssertion': saml_assertion,
        'DurationSeconds': int(duration.total_seconds()),
    }).encode()

    request = urllib.request.Request(_STS_URL, data=params, method='POST')
    request.add_header('Content-Type', 'application/x-www-form-urlencoded')

    try:
        response = urllib.request.urlopen(request)
    except urllib.error.HTTPError as exc:
        try:
            tree = ET.parse(exc)
            message = tree.findtext(f'.//{{{_STS_NS}}}Message', '') or tree.findtext(
                './/Message', ''
            )
        except ET.ParseError:
            message = ''
        raise AuthError(
            f'🐕 STS AssumeRoleWithSAML failed: {message or exc}\n'
            'Are you in the correct Rover group for cockpit-ci-images access?'
        ) from exc

    with response:
        return response.read().decode()


def _parse_sts_response(xml: str) -> tuple[S3Key, datetime]:
    """Parse an STS AssumeRoleWithSAML XML response.

    Returns (S3Key, expiration).  Raises AuthError if the XML is malformed
    or missing fields.
    """
    try:
        tree = ET.fromstring(xml)

        def text(tag: str) -> str:
            if val := tree.findtext(f'.//{{{_STS_NS}}}Credentials/{{{_STS_NS}}}{tag}'):
                return val
            raise AuthError(f'🤔 STS XML response missing {tag}')

        expiration = datetime.fromisoformat(text('Expiration'))
        key = S3Key(text('AccessKeyId'), text('SecretAccessKey'), text('SessionToken'))
        return key, expiration

    except (ET.ParseError, ValueError, TypeError) as exc:
        raise AuthError('🤔 failed to parse STS response') from exc


def cache_path(role_name: str) -> Path:
    """Return the cache file path for STS credentials."""
    return Path(xdg_cache_home('cockpit-dev', 'sts-credentials', f'{role_name}.xml'))


def save_to_cache(role_name: str, xml: str) -> tuple[S3Key, datetime]:
    """Parse, validate, and cache STS credentials.  Returns (key, expiration)."""
    key, expiration = _parse_sts_response(xml)
    path = cache_path(role_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as fp:
        fp.write(xml)
    logger.debug('cached STS credentials to %r (expires %s)', path, expiration)
    return key, expiration


def load_from_cache(role_name: str) -> S3Key | None:
    """Load cached STS credentials if they exist and aren't expiring within 5 minutes."""
    try:
        key, expiration = _parse_sts_response(cache_path(role_name).read_text())
    except (FileNotFoundError, AuthError) as exc:
        logger.debug('cached credentials unusable: %r', exc)
        return None
    if expiration - datetime.now(timezone.utc) < timedelta(minutes=5):
        logger.debug('cached credentials expiring soon (%s)', expiration)
        return None
    return key


@dataclasses.dataclass
class SAMLTarget:
    idp_url: str
    provider_arn: str
    account_id: str
    role: str
    max_session_duration: timedelta


# Red Hat employee IdP (SAML via Kerberos) → AWS IAM role for cockpit-ci-images
# Rover group: https://rover.redhat.com/groups/group/it-cloud-aws-727920394381-cockpit-ci-images-download
TARGETS = {
    'https://cockpit-ci-images*.s3.*.amazonaws.com/rhel-*': SAMLTarget(
        idp_url=REDHAT_SSO_IDP_URL,
        provider_arn=REDHAT_SSO_SAML_PROVIDER_ARN,
        account_id=ACCOUNT_ID,
        role=REDHAT_SSO_IMAGE_DOWNLOAD_ROLE,
        max_session_duration=REDHAT_SSO_IMAGE_DOWNLOAD_MAX_SESSION,
    ),
}


def _find_target(url: str) -> SAMLTarget | None:
    for pattern, target in TARGETS.items():
        if fnmatch.fnmatch(url, pattern):
            return target
    return None


def try_key(url: str, use_cache: bool = True) -> S3Key | None:
    """Return STS credentials if the URL matches a known SAML-authenticated resource."""
    target = _find_target(url)
    if target is None:
        return None

    if use_cache:
        if key := load_from_cache(target.role):
            return key

    saml = _get_saml_assertion(target.idp_url)
    xml = aws_sts_assume_role(target.account_id, target.role, target.provider_arn, saml, target.max_session_duration)

    key, _expiration = save_to_cache(role_name, xml)
    return key
