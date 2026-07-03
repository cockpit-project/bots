# This file is public domain (CC0-1.0)

# Adapted from examples in
# https://s3.amazonaws.com/doc/s3-developer-guide/RESTAuthentication.html
# and
# https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-authenticating-requests.html

import hashlib
import hmac
import http.client
import logging
import os.path
import shlex
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple

from .directories import xdg_config_home
from .network import host_ssl_context

__all__ = (
    "S3Key",
    "get_key",
    "list_bucket",
    "parse_list",
    "s3_sign",
    "sign_curl",
    "sign_url",
    "urlopen",
)


class S3Key(NamedTuple):
    access: str
    secret: str
    token: str | None = None

    def __str__(self) -> str:
        return ' '.join(v for v in self if v is not None)


SHA256_NIL = hashlib.sha256(b'').hexdigest()

logger = logging.getLogger('s3')


def get_key(url: urllib.parse.ParseResult) -> S3Key | None:
    s3_key_dir = xdg_config_home('cockpit-dev/s3-keys', envvar='COCKPIT_S3_KEY_DIR')

    if url.hostname is None:
        return None
    hostname = url.hostname

    # ie: 'cockpit.s3.example.com' then 's3.example.com', then 'example.com'
    while '.' in hostname:
        try:
            with open(os.path.join(s3_key_dir, hostname)) as fp:
                return S3Key(*fp.read().split())
        except (TypeError, ValueError):
            print(f'ignoring invalid content of {s3_key_dir}/{hostname}', file=sys.stderr)
        except FileNotFoundError:
            pass
        _, _, hostname = hostname.partition('.')  # strip a leading component

    return None


def s3_sign(
    hostname: str,
    path: str,
    query: str,
    method: str,
    headers: Mapping[str, str],
    checksum: str,
    key: S3Key,
) -> dict[str, str]:
    """Signs an AWS request using the AWS4-HMAC-SHA256 algorithm

    Returns a dictionary of extra headers which need to be sent along with the request.
    If the method is PUT then the checksum of the data to be uploaded must be provided.
    @headers, if given, are a dict of additional headers to be signed (eg: `x-amz-acl`)
    """
    amzdate = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())

    # Extract region from hostname for AWS S3 (e.g., 's3.us-east-1.amazonaws.com' -> 'us-east-1')
    # AWS requires the actual region; other S3-compatible services accept 'any'
    region = 'any'
    if hostname.endswith('.amazonaws.com'):
        region = hostname.split('.')[-3]

    # Header canonicalisation demands all header names in lowercase
    headers = {k.lower(): v for k, v in headers.items()}
    headers.update({
        'host': hostname,
        'x-amz-content-sha256': checksum,
        'x-amz-date': amzdate,
        **({'x-amz-security-token': key.token} if key.token is not None else {}),
    })
    headers_str = ''.join(f'{k}:{v}\n' for k, v in sorted(headers.items()))
    headers_list = ';'.join(sorted(headers))

    credential_scope = f'{amzdate[:8]}/{region}/s3/aws4_request'
    signing_key = f'AWS4{key.secret}'.encode('ascii')
    for item in credential_scope.split('/'):
        signing_key = hmac.new(signing_key, item.encode('ascii'), hashlib.sha256).digest()

    algorithm = 'AWS4-HMAC-SHA256'
    canonical_request = f'{method}\n{path}\n{query}\n{headers_str}\n{headers_list}\n{checksum}'
    logger.debug('canonical request: %r', canonical_request)
    request_hash = hashlib.sha256(canonical_request.encode('ascii')).hexdigest()
    string_to_sign = f'{algorithm}\n{amzdate}\n{credential_scope}\n{request_hash}'
    signature = hmac.new(signing_key, string_to_sign.encode('ascii'), hashlib.sha256).hexdigest()
    headers['Authorization'] = (
        f'{algorithm} Credential={key.access}/{credential_scope},SignedHeaders={headers_list},Signature={signature}'
    )

    return headers


def sign_request(
    url: urllib.parse.ParseResult,
    method: str,
    headers: Mapping[str, str],
    checksum: str,
    key: S3Key,
) -> dict[str, str]:
    assert url.hostname is not None
    return s3_sign(url.hostname, url.path, url.query, method, headers, checksum, key)


def sign_curl(
    url: urllib.parse.ParseResult,
    method: str = 'GET',
    headers: Mapping[str, str] = {},
    checksum: str = SHA256_NIL,
    key: S3Key | None = None,
) -> Sequence[str]:
    """Same as sign_request() but formats the result as an argument list for curl, including the url"""
    if key is None:
        return [url.geturl()]
    signed = sign_request(url, method, headers, checksum, key=key)
    return [f'-H{k}:{v}' for k, v in signed.items()] + [url.geturl()]


def urlopen(
    url: urllib.parse.ParseResult,
    method: str = 'GET',
    headers: Mapping[str, str] = {},
    data: bytes = b'',
    key: S3Key | None = None,
) -> http.client.HTTPResponse:
    """Perform an S3 HTTP request, optionally signing it.

    If key is given, signs the request.  Otherwise makes a plain unsigned request.
    """
    retries = 0
    while True:
        if key is not None:
            headers = sign_request(url, method, headers, hashlib.sha256(data).hexdigest(), key=key)
        request = urllib.request.Request(url.geturl(), headers=dict(headers), method=method, data=data)
        try:
            result = urllib.request.urlopen(request, context=host_ssl_context(url.netloc), timeout=10)
            return result
        except urllib.error.HTTPError as exc:
            logger.debug('%s %s %s attempt #%i → %s:', method, url.geturl(), headers, retries, exc.status)
            logger.debug('  %s', exc.read())
            if exc.status == 503:
                if retries <= 3:
                    # 1 → 4 → 16 → 64 s back-off
                    time.sleep(4**retries)
                    retries += 1
                    continue
            raise


def list_bucket(url: urllib.parse.ParseResult, key: S3Key | None = None) -> ET.Element:
    """Get the ListBucketResult as a xml.etree.ElementTree"""
    with urlopen(url, key=key) as response:
        return ET.fromstring(response.read())


def parse_list(result: ET.Element, *keys: str) -> Iterable[Iterable[str]]:
    """For each item in the bucket, return the given keys"""
    # 'http' url is API: see https://doc.s3.amazonaws.com/2006-03-01/AmazonS3.wsdl
    xmlns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
    for child in result.findall('s3:Contents', xmlns):
        yield ((attr is not None and attr.text) or '' for attr in (child.find(f's3:{key}', xmlns) for key in keys))


def sign_url(
    url: urllib.parse.ParseResult,
    method: str = 'GET',
    headers: Sequence[str] = (),
    duration: int = 12 * 60 * 60,
    *,
    key: S3Key,
) -> str:
    """Returns a "pre-signed" url for the given method and headers, using AWS4-HMAC-SHA256"""
    assert url.hostname is not None
    access_key, secret_key, session_token = key

    amzdate = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())

    region = 'any'
    if url.hostname.endswith('.amazonaws.com'):
        region = url.hostname.split('.')[-3]

    credential_scope = f'{amzdate[:8]}/{region}/s3/aws4_request'
    credential = f'{access_key}/{credential_scope}'

    # Parse "key:value" header strings and add the required host header
    signed_headers: dict[str, str] = {k.lower(): v for h in headers for k, v in [h.split(':', 1)]}
    signed_headers['host'] = url.hostname
    headers_str = ''.join(f'{k}:{v}\n' for k, v in sorted(signed_headers.items()))
    headers_list = ';'.join(sorted(signed_headers))

    # Query parameters must be sorted for canonical request
    query_params = {
        'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
        'X-Amz-Credential': credential,
        'X-Amz-Date': amzdate,
        'X-Amz-Expires': str(duration),
        'X-Amz-SignedHeaders': headers_list,
        **({'X-Amz-Security-Token': session_token} if session_token is not None else {}),
    }
    query_string = urllib.parse.urlencode(sorted(query_params.items()), quote_via=urllib.parse.quote)

    canonical_request = f'{method}\n{url.path}\n{query_string}\n{headers_str}\n{headers_list}\nUNSIGNED-PAYLOAD'
    logger.debug('canonical request: %r', canonical_request)

    algorithm = 'AWS4-HMAC-SHA256'
    request_hash = hashlib.sha256(canonical_request.encode('ascii')).hexdigest()
    string_to_sign = f'{algorithm}\n{amzdate}\n{credential_scope}\n{request_hash}'

    signing_key = f'AWS4{secret_key}'.encode('ascii')
    for item in credential_scope.split('/'):
        signing_key = hmac.new(signing_key, item.encode('ascii'), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode('ascii'), hashlib.sha256).hexdigest()

    return url._replace(query=f'{query_string}&X-Amz-Signature={signature}').geturl()


def main() -> None:
    # to be used like `python3 -m lib.s3 get https://...` from the toplevel dir
    _prognam, cmd, uri = sys.argv

    url = urllib.parse.urlparse(uri)

    key = get_key(url)
    if key is None:
        sys.exit(f'no key is available for {url.hostname}')

    if cmd == 'get':
        args = sign_curl(url, key=key)
    elif cmd == 'url':
        print(sign_url(url, key=key))
        sys.exit(0)
    elif cmd == 'ls':
        for items in parse_list(list_bucket(url, key=key), "Size", "LastModified", "Key"):
            print('\t'.join(items))
        sys.exit(0)
    elif cmd == 'rm':
        args = ["-XDELETE", *sign_curl(url, method="DELETE", key=key)]
    elif cmd == 'put':
        args = [sign_url(url, method='PUT', key=key)]
    else:
        sys.exit(f'unknown command {cmd}')

    print('curl', shlex.join(args))


if __name__ == '__main__':
    main()
