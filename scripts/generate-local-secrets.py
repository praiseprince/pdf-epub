from __future__ import annotations

import secrets
import sys

import bcrypt


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate-local-secrets.py <your-pin-or-passcode>", file=sys.stderr)
        return 1

    pin = sys.argv[1]
    if len(pin) < 8:
        print("Use at least eight characters for the local app PIN.", file=sys.stderr)
        return 1

    pin_hash = bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    print(f"APP_PIN_HASH={pin_hash}")
    print(f"SESSION_SECRET={secrets.token_urlsafe(32)}")
    print("")
    print("Store these values once. Do not commit .env or .env.local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
