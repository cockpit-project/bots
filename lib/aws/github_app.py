# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import base64
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import httpx

from lib import testmap

from ..aio.jsonutil import (
    JsonObject,
    JsonValue,
    get_dictv,
    get_int,
    get_nested,
    get_str,
    typechecked,
)
from .account import CI_RUNNER_REGION, GITHUB_APP_KMS_ALIAS

GITHUB_APP_CLIENT_ID = "Iv23liDMkgxMtqfpmGvu"


class GithubAPI:
    @property
    def token(self) -> str:
        raise NotImplementedError

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def request(
        self,
        method: str,
        path: str,
        *,
        body: JsonObject | None = None,
    ) -> JsonValue:
        response = self.client.request(
            method,
            httpx.URL("https://api.github.com/").join(path),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "cockpit-ci",
            },
            json=body,
        )

        response.raise_for_status()

        return response.json()

    def post_obj(self, path: str, body: JsonObject) -> JsonObject:
        return typechecked(self.request("POST", path, body=body), dict)

    def get_obj(self, path: str) -> JsonObject:
        return typechecked(self.request("GET", path), dict)

    def get_objv(self, path: str) -> Sequence[JsonObject]:
        return tuple(
            typechecked(item, dict)
            for item in typechecked(self.request("GET", path), list)
        )


# https://docs.github.com/en/rest/apps/installations
class GithubAppInstallation(GithubAPI):
    def __init__(self, client: httpx.Client, token: str) -> None:
        super().__init__(client)
        self._token = token

    @property
    def token(self) -> str:
        return self._token


# https://docs.github.com/en/rest/apps/apps
class GithubApp(GithubAPI):
    iid_cache = "", 0
    jwt = "", 0

    def sign_jwt(self, payload: bytes) -> bytes:
        raise NotImplementedError

    def mint_jwt(self, now: int) -> str:
        def b64(data: bytes | JsonObject) -> str:
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        # https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
        header = b64({"alg": "RS256", "typ": "JWT"})
        payload = b64({"iss": GITHUB_APP_CLIENT_ID, "iat": now - 60, "exp": now + 540})
        signature = b64(self.sign_jwt(f"{header}.{payload}".encode()))

        # Standard JWT dotted header.payload.signature format
        return f"{header}.{payload}.{signature}"

    @property
    def token(self) -> str:
        now = int(time.time())
        cached, expiry = self.jwt
        if now < expiry:
            return cached

        jwt = self.mint_jwt(now)
        self.jwt = jwt, now + 5 * 60
        return jwt

    def find_installation(self, org: str) -> int:
        cached_org, cached_iid = self.iid_cache
        if org == cached_org:
            return cached_iid

        iid = get_int(self.get_obj(f"/orgs/{org}/installation"), "id")
        self.iid_cache = org, iid
        return iid

    def get_installation(
        self,
        installation: int | str,
        *,
        repositories: Sequence[str] = (),
        permissions: Mapping[str, Literal["read", "write"]] = {},
    ) -> GithubAppInstallation:
        if isinstance(installation, str):
            # lookup by organisation name
            installation = self.find_installation(installation)

        response = self.post_obj(
            f"/app/installations/{installation}/access_tokens",
            {"repositories": repositories, "permissions": permissions},
        )
        return GithubAppInstallation(client, get_str(response, "token"))


class KMSGithubApp(GithubApp):
    def __init__(self, client: httpx.Client):
        import boto3

        super().__init__(client)
        self.kms = boto3.client("kms", region_name=CI_RUNNER_REGION)

    def sign_jwt(self, payload: bytes) -> bytes:
        # https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html
        return self.kms.sign(
            KeyId=GITHUB_APP_KMS_ALIAS,
            Message=payload,
            MessageType="RAW",
            SigningAlgorithm="RSASSA_PKCS1_V1_5_SHA_256",
        )["Signature"]


class FileGithubApp(GithubApp):
    def __init__(self, client: httpx.Client, path: Path) -> None:
        super().__init__(client)
        self.path = path

    def sign_jwt(self, payload: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        key = serialization.load_pem_private_key(self.path.read_bytes(), password=None)
        assert isinstance(key, rsa.RSAPrivateKey)

        return key.sign(payload, padding.PKCS1v15(), hashes.SHA256())


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()

    with httpx.Client() as client:
        app = KMSGithubApp(client)

        print(json.dumps(app.get_obj("/app"), indent=4))

        installed_projects = set()
        print("\nInstallations:")
        for i_info in app.get_objv("/app/installations"):
            with get_nested(i_info, "account") as account:
                login = get_str(account, "login")

            print(f"  - {login}")

            installation = app.get_installation(
                get_int(i_info, "id"),
                permissions={"metadata": "read"},
            )
            repositories = installation.get_obj("/installation/repositories")

            for repo in get_dictv(repositories, "repositories"):
                installed_projects.add(get_str(repo, "full_name"))
                print(f"    - {get_str(repo, 'name')}")

            print()

    testmap_projects = set(testmap.projects())

    if diff := testmap_projects.difference(installed_projects):
        print("In testmap, but not installed:", diff)

    if diff := installed_projects.difference(testmap_projects):
        print("Installed, but not in testmap:", diff)
