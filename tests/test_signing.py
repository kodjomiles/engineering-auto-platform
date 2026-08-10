from engineering_automation.webhooks.signing import sign, signature_payload, verify


def test_signature_payload_separates_timestamp_and_body() -> None:
    assert signature_payload(1_700_000_000, b'{"ok":true}') == b'1700000000.{"ok":true}'


def test_signing_is_deterministic() -> None:
    assert sign(b"secret", 1_700_000_000, b"body") == sign(b"secret", 1_700_000_000, b"body")


def test_signature_has_algorithm_prefix() -> None:
    signature = sign(b"secret", 1_700_000_000, b"body")
    assert signature.startswith("sha256=")
    assert len(signature) == len("sha256=") + 64


def test_verification_accepts_valid_signature() -> None:
    signature = sign(b"secret", 1_700_000_000, b"body")
    assert verify(b"secret", 1_700_000_000, b"body", signature)


def test_verification_rejects_changed_body() -> None:
    signature = sign(b"secret", 1_700_000_000, b"body")
    assert not verify(b"secret", 1_700_000_000, b"changed", signature)


def test_verification_rejects_changed_timestamp() -> None:
    signature = sign(b"secret", 1_700_000_000, b"body")
    assert not verify(b"secret", 1_700_000_001, b"body", signature)


def test_verification_rejects_changed_secret() -> None:
    signature = sign(b"secret", 1_700_000_000, b"body")
    assert not verify(b"other", 1_700_000_000, b"body", signature)
