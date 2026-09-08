"""Cryptographic and request-level protections.

Nothing in here invents a primitive. Password hashing is argon2-cffi, token signing is
PyJWT, randomness is :mod:`secrets`. What this package contributes is the *policy* around
them: how long a token lives, what happens when one is replayed, and how a limit is
counted so that it is one limit per client rather than one per replica.
"""
