"""Stable content hashes for retrieval/ranking/attribution fields.

These are not marketing version labels. Changing the hashed payload changes the
value; callers persist whatever the current spec hashes to.
"""
from hashlib import sha256

from smartlect.events import canonical


def content_hash(payload):
    return sha256(canonical(payload).encode()).hexdigest()[:16]
