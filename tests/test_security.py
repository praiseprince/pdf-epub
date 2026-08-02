from __future__ import annotations

from pathlib import Path

from local_app.security import hash_pin, verify_pin, write_local_secrets
from local_app.config import Settings


def test_write_local_secrets_preserves_other_settings(tmp_path: Path) -> None:
    config = tmp_path / ".env"
    config.write_text("LOCAL_PADDLE_MODE=local\nAPP_PIN_HASH=old\nSESSION_SECRET=old\n", encoding="utf-8")
    pin_hash = hash_pin("123456")

    write_local_secrets(config, pin_hash=pin_hash, session_secret="secret")

    content = config.read_text(encoding="utf-8")
    assert "LOCAL_PADDLE_MODE=local" in content
    assert "APP_PIN_HASH=old" not in content
    assert "SESSION_SECRET=old" not in content
    assert verify_pin("123456", Settings(APP_PIN_HASH=pin_hash, SESSION_SECRET="secret"))
