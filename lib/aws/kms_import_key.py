# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import hashlib
import os
import secrets
import tempfile
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.keywrap import aes_key_wrap_with_padding

from .account import CI_RUNNER_REGION, GITHUB_APP_KMS_ALIAS, TAGS

RSAES_OAEP_SHA_256 = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)


def get_key_from_human() -> bytes:
    # We're sort of stuck with a terrible approach here:
    #
    #  - instead of generating a key (eg: inside of the AWS KMS HSM) we need to
    #    download the private key that GitHub generated for us.  See the open
    #    discussion: https://github.com/orgs/community/discussions/176838
    #
    #  - there's no API endpoint we can use to do this: it has to be done in
    #    the browser
    #
    # The result of all of that is that the "best practice" for this is that
    # Firefox ends up popping up a download dialog offering to put our shiny
    # new private key, unencrypted, in the user's Downloads folder.  Not great.
    #
    # We can mitigate things a bit by creating a temporary directory on a tmpfs
    # and telling the user to download to that location, deleting the file
    # ASAP. That means the unencrypted material will at least never touch a
    # disk, and won't be exposed to other processes for longer than necessary.

    with tempfile.TemporaryDirectory(dir=os.environ["XDG_RUNTIME_DIR"]) as temp:
        today = time.strftime("%Y-%m-%d")
        private_key_path = Path(temp) / f"cockpit-ci.{today}.private-key.pem"

        print(
            "Go here:",
            "    https://github.com/organizations/cockpit-project/settings/apps/cockpit-ci/key_pairs",
            "Then click on \x1b[48;5;22m\x1b[38;5;15m New key \033[0m",
            "Download to:",
            f"  - folder: {temp}",
            f"  - name: {private_key_path.name}",
            f"  - full filename: {private_key_path}",
            "I'll wait here.",
            sep="\n\n",
            end="\n\n",
        )

        # Wait for the file to appear at the expected location
        while True:
            try:
                pem = private_key_path.read_bytes()
                private_key_path.unlink()  # not strictly necessary...
            except FileNotFoundError:
                time.sleep(0.1)
                continue
            break

        print("Got it, thanks!  (and deleted it)", end="\n\n")

    # GitHub sends PEM but AWS wants DER
    private_key = serialization.load_pem_private_key(pem, password=None)
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def update_github_app_key() -> None:
    kms = boto3.client("kms", region_name=CI_RUNNER_REGION)

    # Step 1: look if the alias points to an existing key, and make note of it
    old_key_id: str | None = None
    old_key_fingerprint: str | None = None
    try:
        desc = kms.get_public_key(KeyId=GITHUB_APP_KMS_ALIAS)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NotFoundException":
            raise
        print(f"{GITHUB_APP_KMS_ALIAS} doesn't exist yet.")
    else:
        old_key_id = desc["KeyId"]
        digest = hashlib.sha256(desc["PublicKey"]).digest()
        old_key_fingerprint = "SHA256:" + base64.b64encode(digest).decode()
        print(
            "⚠️  This will replace",
            f"    {old_key_fingerprint}",
            "and schedule it for deletion!",
            sep="\n\n",
            end="\n\n",
        )

    # Step 2: get the new key from the human.  We want to do this after we know
    # that we have the credentials to talk to KMS (as we just did above) but
    # before we actually create the new key (in case the user wants to abort
    # the process).
    key_der = get_key_from_human()

    # Step 3a: create a fresh key (no key material yet)
    # https://docs.aws.amazon.com/kms/latest/developerguide/importing-keys-create-cmk.html
    resp = kms.create_key(
        Description="https://github.com/apps/cockpit-ci",
        KeySpec="RSA_2048",
        KeyUsage="SIGN_VERIFY",
        Origin="EXTERNAL",
        Tags=[{"TagKey": k, "TagValue": v} for k, v in TAGS.items()],
    )
    key_id = resp["KeyMetadata"]["KeyId"]
    print(f" - created new KMS key: {key_id}")

    # Step 3b: in order to import, we need the import token and wrapping key
    # https://docs.aws.amazon.com/kms/latest/developerguide/importing-keys-get-public-key-and-token.html
    #
    # We can't use straight RSAES_OAEP_SHA_256 for RSA keys so we need to go
    # with the RSA_AES_KEY_WRAP_SHA_256 route which essentially involves
    # RSAES_OAEP_SHA_256 for an ephemeral AES key which then encrypts the RSA
    # private key data (as DER)
    params = kms.get_parameters_for_import(
        KeyId=key_id,
        WrappingAlgorithm="RSA_AES_KEY_WRAP_SHA_256",
        WrappingKeySpec="RSA_4096",  # "recommended"
    )
    wrapping_key = serialization.load_der_public_key(params["PublicKey"])
    assert isinstance(wrapping_key, rsa.RSAPublicKey)
    print("    - got import parameters")

    # Step 3c: encrypt our (GitHub) key to KMS
    # https://docs.aws.amazon.com/kms/latest/developerguide/importing-keys-encrypt-key-material.html
    aes_key = secrets.token_bytes(32)
    encrypted_aes = wrapping_key.encrypt(aes_key, RSAES_OAEP_SHA_256)
    wrapped_key = aes_key_wrap_with_padding(wrapping_key=aes_key, key_to_wrap=key_der)
    del aes_key

    # Step 2d: send the wrapped key for import, using the import token
    # https://docs.aws.amazon.com/kms/latest/developerguide/importing-keys-import-key-material.html
    kms.import_key_material(
        KeyId=key_id,
        ImportToken=bytes(params["ImportToken"]),
        EncryptedKeyMaterial=encrypted_aes + wrapped_key,
        ExpirationModel="KEY_MATERIAL_DOES_NOT_EXPIRE",
    )
    print("    - imported key material")

    # Step 3: Update or create the alias to point to our key
    if old_key_id is not None:
        kms.update_alias(AliasName=GITHUB_APP_KMS_ALIAS, TargetKeyId=key_id)
    else:
        kms.create_alias(AliasName=GITHUB_APP_KMS_ALIAS, TargetKeyId=key_id)
    print(f"  - {GITHUB_APP_KMS_ALIAS} → {key_id}")

    # Step 5: only after all that worked, mark the old key for deletion
    if old_key_id is not None:
        kms.schedule_key_deletion(KeyId=old_key_id, PendingWindowInDays=7)
        print(f"  - {old_key_id} scheduled for deletion")

    if old_key_fingerprint is not None:
        print()
        print(
            "You should verify that the new key is functioning properly and delete",
            f"    {old_key_fingerprint}",
            "from the GitHub App settings page.",
            sep="\n\n",
            end="\n\n",
        )


if __name__ == "__main__":
    import argparse
    argparse.ArgumentParser().parse_args()
    update_github_app_key()
