"""RFC 6238 Appendix B interoperability; no identity or production assurance."""

import unittest

from cryptography.fernet import Fernet

from . import crypto


class PrimitiveTests(unittest.TestCase):
    def test_rfc_6238_appendix_b_all_eighteen_reference_vectors(self):
        # RFC 6238 Appendix B, with the 20/32/64-byte seeds from its reference
        # implementation. https://www.rfc-editor.org/rfc/rfc6238.html#appendix-B
        vectors = (
            (59, "94287082", "46119246", "90693936"),
            (1111111109, "07081804", "68084774", "25091201"),
            (1111111111, "14050471", "67062674", "99943326"),
            (1234567890, "89005924", "91819424", "93441116"),
            (2000000000, "69279037", "90698825", "38618901"),
            (20000000000, "65353130", "77737706", "47863826"),
        )
        for stamp, *tokens in vectors:
            for algorithm, size, expected in zip(
                ("SHA1", "SHA256", "SHA512"), (20, 32, 64), tokens, strict=True
            ):
                secret = (b"1234567890" * 7)[:size]
                with self.subTest(stamp=stamp, algorithm=algorithm):
                    common = dict(secret=secret, algorithm=algorithm, digits=8, period=30)
                    self.assertEqual(crypto.generate(**common, at=stamp), expected)
                    self.assertEqual(
                        crypto.match(**common, code=expected, at=stamp, window=0), stamp // 30
                    )

    def test_exact_ascii_token_and_explicit_finite_clock_window(self):
        common = dict(secret=b"12345678901234567890", algorithm="SHA1", digits=8, period=30)
        self.assertEqual(crypto.match(**common, code="94287082", at=60, window=1), 1)
        self.assertIsNone(crypto.match(**common, code="94287082", at=60, window=0))
        self.assertIsNone(crypto.match(**common, code="94287082", at=90, window=1))
        for code in (" 94287082", "94287082\n", "٩٤٢٨٧٠٨٢", "9428708", "abcdefgh", None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                crypto.match(**common, code=code, at=59, window=0)
        for window in (-1, 2, True):
            with self.subTest(window=window), self.assertRaises(ValueError):
                crypto.match(**common, code="94287082", at=59, window=window)

    def test_authenticated_encryption_is_bound_to_the_exact_factor(self):
        key = Fernet.generate_key()
        secret, binding = b"12345678901234567890", "a" * 64
        cipher = crypto.seal(secret=secret, key=key, binding=binding)
        self.assertNotIn(secret.decode(), cipher)
        self.assertEqual(crypto.unseal(cipher=cipher, key=key, binding=binding), secret)
        for changes in (
            {"key": Fernet.generate_key()},
            {"binding": "b" * 64},
            {"cipher": cipher[:-5] + "AAAAA"},
            {"cipher": cipher[:20]},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError):
                crypto.unseal(**{"cipher": cipher, "key": key, "binding": binding, **changes})

    def test_no_unbounded_or_weak_parameters(self):
        common = dict(secret=b"12345678901234567890", algorithm="SHA1", digits=8, period=30, at=59)
        for changes in (
            {"secret": b"short"},
            {"algorithm": "MD5"},
            {"digits": 5},
            {"digits": True},
            {"period": 0},
            {"period": 3600},
            {"at": -1},
            {"at": True},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError):
                crypto.generate(**{**common, **changes})
