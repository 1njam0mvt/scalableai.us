"""
Generates the JWT that Apple calls a "client secret" for Sign in with Apple.

Unlike Google/GitHub, Apple doesn't give you a static client secret string.
Instead you generate a JWT yourself, signed with a private key Apple gives
you when you create a "Sign in with Apple" key in the Apple Developer
portal. That JWT is valid for at most 6 months, so this needs to be re-run
periodically (see DEPLOY.md) and the result placed in APPLE_CLIENT_SECRET.

Usage:
    pip install pyjwt cryptography --break-system-packages
    python scripts/generate_apple_client_secret.py \
        --team-id ABCDE12345 \
        --client-id us.scalableai.web \
        --key-id XYZ98765 \
        --key-file /path/to/AuthKey_XYZ98765.p8

Prints the JWT to stdout — copy it into APPLE_CLIENT_SECRET.
"""

import argparse
import time

import jwt  # PyJWT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", required=True, help="Your Apple Developer Team ID")
    parser.add_argument("--client-id", required=True, help="Your Services ID (e.g. us.scalableai.web)")
    parser.add_argument("--key-id", required=True, help="The Key ID of your Sign in with Apple private key")
    parser.add_argument("--key-file", required=True, help="Path to the downloaded AuthKey_XXXXX.p8 file")
    parser.add_argument("--days", type=int, default=180, help="Validity period in days (Apple's max is ~180)")
    args = parser.parse_args()

    with open(args.key_file, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iss": args.team_id,
        "iat": now,
        "exp": now + args.days * 24 * 60 * 60,
        "aud": "https://appleid.apple.com",
        "sub": args.client_id,
    }
    headers = {"kid": args.key_id, "alg": "ES256"}

    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    print(token)


if __name__ == "__main__":
    main()