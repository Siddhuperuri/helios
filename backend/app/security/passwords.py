"""Password hashing.

Argon2id, via argon2-cffi. The algorithm is not a choice this module makes so much as one
it declines to re-litigate: Argon2id is the current OWASP first recommendation, it is
memory-hard, and argon2-cffi is the reference binding.

Two behaviours here are easy to leave out and both matter:

*Rehash on login.* Work factors are raised over time as hardware gets faster. A hash
written under the old parameters is still valid but no longer strong enough, and the only
moment the plaintext is available to upgrade it is during a successful login. So that is
when it happens.

*Constant work on a missing user.* Verifying against nothing returns instantly, while
verifying against a real hash takes tens of milliseconds. That difference is enough to
enumerate which addresses have accounts. :func:`verify` is therefore always called, against
a dummy hash when there is no user.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _hasher() -> PasswordHasher:
    auth = get_settings().auth
    return PasswordHasher(
        time_cost=auth.argon2_time_cost,
        memory_cost=auth.argon2_memory_kib,
        parallelism=auth.argon2_parallelism,
    )


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A real hash of a value nobody will ever submit.

    Its only purpose is to be verified against when the account does not exist, so that
    the request costs the same either way.
    """
    return _hasher().hash("helios-timing-equalisation-value")


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    """Check a password. Takes the same time whether or not there is a hash to check."""
    hasher = _hasher()
    if not hashed:
        try:
            hasher.verify(_dummy_hash(), password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass
        return False
    try:
        return hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False
    except InvalidHashError:
        # A stored value that is not an Argon2 hash at all. Treat as a failed login and
        # say so loudly, because it means something wrote to the column that should not
        # have.
        logger.error("Stored password hash is not in a recognised format")
        return False


def needs_rehash(hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher().check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def reset_cache() -> None:
    """Drop the cached hasher after a settings change. Tests only."""
    _hasher.cache_clear()
    _dummy_hash.cache_clear()


# --------------------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------------------

def password_problem(password: str) -> str | None:
    """Why this password is not acceptable, or ``None`` if it is.

    Length is the requirement, and deliberately the only one. Composition rules —
    an uppercase, a digit, a symbol — measurably push people towards `Password1!` and are
    no longer recommended by NIST or OWASP. A longer minimum buys more than a character-class
    rule does.
    """
    auth = get_settings().auth
    if len(password) < auth.min_password_length:
        return (
            f"Use at least {auth.min_password_length} characters. A short phrase you will "
            f"remember is stronger than a short word with symbols in it."
        )
    if len(password) > auth.max_password_length:
        return f"That password is longer than the {auth.max_password_length}-character limit."
    if password.strip() == "":
        return "A password cannot be only spaces."
    return None
