def remove_prefix(s: str, prefix: str) -> str:
    if not s.startswith(prefix):
        return s

    return s[len(prefix) :]


def remove_suffix(s: str, suffix: str) -> str:
    if not s.endswith(suffix):
        return s

    return s[: -len(suffix)]
