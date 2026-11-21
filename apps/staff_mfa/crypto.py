"""Bounded RFC 6238 and Fernet calls; replay/attempt policy lives in the ledger."""

import base64
import json
import re
from hmac import compare_digest

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor.totp import TOTP

ALGORITHMS = {"SHA1": hashes.SHA1, "SHA256": hashes.SHA256, "SHA512": hashes.SHA512}


def _parameters(secret, algorithm, digits, period, at):
    if (
        type(secret) is not bytes
        or len(secret) not in {20, 32, 64}
        or type(algorithm) is not str
        or algorithm not in ALGORITHMS
        or type(digits) is not int
        or digits not in {6, 8}
        or type(period) is not int
        or period not in {30, 60}
        or type(at) is not int
        or not 0 <= at < 2**64
    ):
        raise ValueError("mfa_otp_parameters_invalid")
    return TOTP(secret, digits, ALGORITHMS[algorithm](), period)


def generate(*, secret, algorithm, digits, period, at):
    return _parameters(secret, algorithm, digits, period, at).generate(at).decode("ascii")


def match(*, secret, algorithm, digits, period, code, at, window):
    otp = _parameters(secret, algorithm, digits, period, at)
    if (
        type(code) is not str
        or len(code) != digits
        or not code.isascii()
        or not code.isdigit()
        or type(window) is not int
        or window not in {0, 1}
    ):
        raise ValueError("mfa_otp_token_invalid")
    counter = at // period
    matches = [
        step
        for step in range(max(0, counter - window), counter + window + 1)
        if compare_digest(otp.generate(step * period), code.encode("ascii"))
    ]
    # Ambiguous truncated values across steps never imply two usable proofs.
    return matches[0] if len(matches) == 1 else None


def _cipher(key, binding):
    if (
        type(key) is not bytes
        or len(key) != 44
        or type(binding) is not str
        or re.fullmatch(r"[a-f0-9]{64}", binding) is None
    ):
        raise ValueError("mfa_key_or_binding_invalid")
    return Fernet(key)


def seal(*, secret, key, binding):
    if type(secret) is not bytes or len(secret) not in {20, 32, 64}:
        raise ValueError("mfa_secret_invalid")
    value = json.dumps(
        {"binding": binding, "secret": base64.b64encode(secret).decode("ascii")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return _cipher(key, binding).encrypt(value).decode("ascii")


def unseal(*, cipher, key, binding):
    if type(cipher) is not str or not 100 <= len(cipher) <= 1024 or not cipher.isascii():
        raise ValueError("mfa_sealed_secret_invalid")
    try:
        value = json.loads(_cipher(key, binding).decrypt(cipher.encode("ascii")))
        if (
            type(value) is not dict
            or set(value) != {"binding", "secret"}
            or type(value["binding"]) is not str
            or type(value["secret"]) is not str
            or not compare_digest(value["binding"], binding)
        ):
            raise ValueError("mfa_secret_binding_invalid")
        secret = base64.b64decode(value["secret"], validate=True)
        if len(secret) not in {20, 32, 64}:
            raise ValueError("mfa_secret_invalid")
        return secret
    except (InvalidToken, UnicodeError, TypeError, KeyError) as exc:
        raise ValueError("mfa_sealed_secret_invalid") from exc
