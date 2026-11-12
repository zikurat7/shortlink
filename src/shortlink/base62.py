"""Base62 encoding of non-negative integers, used to turn row IDs into short codes."""

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = len(ALPHABET)
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}


def encode(n: int) -> str:
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return ALPHABET[0]
    digits = []
    while n:
        n, rem = divmod(n, _BASE)
        digits.append(ALPHABET[rem])
    return "".join(reversed(digits))


def decode(s: str) -> int:
    if not s:
        raise ValueError("empty string")
    n = 0
    for ch in s:
        try:
            n = n * _BASE + _INDEX[ch]
        except KeyError:
            raise ValueError(f"invalid base62 character: {ch!r}") from None
    return n
