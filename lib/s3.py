#!/usr/bin/python3

# This file is public domain (CC0-1.0)

# Adapted from examples in
# https://s3.amazonaws.com/doc/s3-developer-guide/RESTAuthentication.html
# and
# https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-authenticating-requests.html

import base64
import hashlib
import hmac
import os.path
import shlex
import sys
import time
import urllib.parse
from typing import Dict, List

from .directories import xdg_config_home

__all__ = (
    "ACL",
    "ACL_PUBLIC",
    "PUBLIC",
    "is_key_present",
    "sign_curl",
    "sign_request",
)

ACL = 'x-amz-acl'
PUBLIC = 'public-read'
ACL_PUBLIC = f'{ACL}:{PUBLIC}'
SHA256_NIL = hashlib.sha256(b'').hexdigest()


def get_key(hostname):
    s3_key_dir = xdg_config_home('cockpit-dev/s3-keys', envvar='COCKPIT_S3_KEY_DIR')

    # ie: 'cockpit-images.eu.linode.com' then 'eu.linode.com', then 'linode.com'
    while '.' in hostname:
        try:
            with open(os.path.join(s3_key_dir, hostname)) as fp:
                access, secret = fp.read().split()
                return access, secret
        except ValueError:
            print('ignoring invalid content of {s3_key_dir}/{hostname}', file=sys.stderr)
        except FileNotFoundError:
            pass
        _, _, hostname = hostname.partition('.')  # strip a leading component

    return None


def is_key_present(url: urllib.parse.ParseResult) -> bool:
    """Checks if an S3 key is available for the given url"""
    return get_key(url.hostname) is not None


def sign_request(url: urllib.parse.ParseResult, method='GET', checksum=SHA256_NIL, headers={}) -> Dict[str, str]:
    """Signs an AWS request using the AWS4-HMAC-SHA256 algorithm

    Returns a dictionary of extra headers which need to be sent along with the request.
    If the method is PUT then the checksum of the data to be uploaded must be provided.
    @headers, if given, are a dict of additional headers to be signed (eg: `x-amz-acl`)
    """
    access_key, secret_key = get_key(url.hostname)

    amzdate = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())

    headers = headers.copy()  # don't modify the user's copy, or the default
    headers.update({'host': url.hostname, 'x-amz-content-sha256': checksum, 'x-amz-date': amzdate})
    headers_str = ''.join(f'{k}:{v}\n' for k, v in sorted(headers.items()))
    headers_list = ';'.join(sorted(headers))

    credential_scope = f'{amzdate[:8]}/any/s3/aws4_request'
    signing_key = f'AWS4{secret_key}'.encode('ascii')
    for item in credential_scope.split('/'):
        signing_key = hmac.new(signing_key, item.encode('ascii'), hashlib.sha256).digest()

    algorithm = 'AWS4-HMAC-SHA256'
    canonical_request = f'{method}\n{url.path}\n{url.query}\n{headers_str}\n{headers_list}\n{checksum}'
    request_hash = hashlib.sha256(canonical_request.encode('ascii')).hexdigest()
    string_to_sign = f'{algorithm}\n{amzdate}\n{credential_scope}\n{request_hash}'
    signature = hmac.new(signing_key, string_to_sign.encode('ascii'), hashlib.sha256).hexdigest()
    headers['Authorization'] = f'{algorithm} Credential={access_key}/{credential_scope},' \
        f'SignedHeaders={headers_list},Signature={signature}'

    return headers


def sign_curl(url: urllib.parse.ParseResult, method='GET', checksum=SHA256_NIL, headers={}) -> List[str]:
    """Same as sign_request() but formats the result as an argument list for curl, including the url"""
    headers = sign_request(url, method=method, checksum=checksum, headers=headers)
    return [f'-H{key}:{value}' for key, value in headers.items()] + [url.geturl()]


def sign_url(url: urllib.parse.ParseResult, method='GET', headers=[], duration=12 * 60 * 60) -> str:
    """Returns a "pre-signed" url for the given method and headers"""
    access, secret = get_key(url.hostname)
    bucket = url.hostname.split('.')[0]

    expires = int(time.time()) + duration
    headers = ''.join(f'{h}\n' for h in headers)

    h = hmac.HMAC(secret.encode('ascii'), digestmod='sha1')
    h.update(f'{method}\n\n\n{expires}\n{headers}/{bucket}{url.path}'.encode('ascii'))
    signature = urllib.parse.quote_plus(base64.b64encode(h.digest()))

    query = f'AWSAccessKeyId={access}&Expires={expires}&Signature={signature}'
    return url._replace(query=query).geturl()


def main():
    # to be used like `python3 -m lib.s3 get https://...` from the toplevel dir
    prognam, cmd, uri = sys.argv

    url = urllib.parse.urlparse(uri)
    if cmd == 'get':
        args = sign_curl(url)
    elif cmd == 'rm':
        args = ['-XDELETE'] + sign_curl(url, method='DELETE')
    elif cmd == 'put':
        args = [sign_url(url, method='PUT')]
    elif cmd == 'put-public':
        args = [sign_url(url, method='PUT', headers=[ACL_PUBLIC])]
    else:
        sys.exit(f'unknown command {cmd}')

    # shlex.join() only from Python 3.8
    print('curl', ' '.join(map(shlex.quote, args)))


if __name__ == '__main__':
    main()
