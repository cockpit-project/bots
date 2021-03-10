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


def split_bucket(url):
    return url.hostname.split('.', 1)


def get_key_filename(endpoint):
    s3_key_dir = xdg_config_home('cockpit-dev/s3-keys', envvar='COCKPIT_S3_KEY_DIR')
    return os.path.join(s3_key_dir, endpoint)


def is_key_present(url):
    try:
        bucket, endpoint = split_bucket(url)
    except ValueError:
        # happens if there is no '.' in the hostname
        return False

    return os.path.exists(get_key_filename(endpoint))


def sign_url(url, verb='GET', headers=[], duration=12 * 60 * 60):
    bucket, endpoint = split_bucket(url)
    access, secret = open(get_key_filename(endpoint)).read().split()

    expires = int(time.time()) + duration
    headers = ''.join(f'{h}\n' for h in headers)

    h = hmac.HMAC(secret.encode('ascii'), digestmod='sha1')
    h.update(f'{verb}\n\n\n{expires}\n{headers}/{bucket}{url.path}'.encode('ascii'))
    signature = urllib.parse.quote_plus(base64.b64encode(h.digest()))

    query = f'AWSAccessKeyId={access}&Expires={expires}&Signature={signature}'
    return url._replace(query=query).geturl()


def main():
    prognam, cmd, uri = sys.argv

    url = urllib.parse.urlparse(uri)
    if cmd == 'get':
        print(sign_url(url))
    elif cmd == 'put':
        print(sign_url(url, verb='PUT'))
    elif cmd == 'put-public':
        print('-H{ACL_PUBLIC}', sign_url(url, verb='PUT', headers=[ACL_PUBLIC]))
    else:
        sys.exit(f'unknown command {cmd}')


if __name__ == '__main__':
    main()
