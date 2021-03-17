#!/usr/bin/python3

# This file is public domain (CC0-1.0)

# Adapted from examples in
# https://s3.amazonaws.com/doc/s3-developer-guide/RESTAuthentication.html

import base64
import hmac
import os.path
import sys
import time
import urllib.parse
from .directories import xdg_config_home

__all__ = (
    "ACL_PUBLIC",
    "is_key_present",
    "sign_url",
)

ACL_PUBLIC = 'x-amz-acl:public-read'


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
    prognam, cmd, uri = sys.argv

    url = urllib.parse.urlparse(uri)
    if cmd == 'get':
        print(sign_url(url))
    elif cmd == 'put':
        print(sign_url(url, method='PUT'))
    elif cmd == 'put-public':
        print('-H{ACL_PUBLIC}', sign_url(url, method='PUT', headers=[ACL_PUBLIC]))
    else:
        sys.exit(f'unknown command {cmd}')


if __name__ == '__main__':
    main()
