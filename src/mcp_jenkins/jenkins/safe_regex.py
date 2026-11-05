"""Compile a user-supplied regular expression only when it can not backtrack catastrophically.

The server runs the pattern on the event loop over log lines of up to 2000 characters, so one pattern such as
``(a|a)*$`` would freeze every tool, including a pending approval. Nested or alternated repeats are refused with a
message that says what to write instead.
"""

import re

MAX_PATTERN_LENGTH = 200

_HINT = 'use literal text, character classes or a simple alternation outside any repeat, for example "ERROR|FAILED"'


def _unsafe_by_text(pattern: str) -> bool:
    """Fallback when the regex parser is unavailable: refuse a repeated group of any kind."""
    return bool(re.search(r'\)[*+]|\)\{', pattern))


def _nested_repeat(items: object, constants: object, *, inside_repeat: bool) -> bool:  # noqa: C901, PLR0911
    """True when a repeat of more than one contains an unbounded repeat or an alternation."""
    maxrepeat = constants.MAXREPEAT
    repeats = {constants.MAX_REPEAT, constants.MIN_REPEAT}
    if hasattr(constants, 'POSSESSIVE_REPEAT'):
        repeats.add(constants.POSSESSIVE_REPEAT)

    for op, av in items:
        if op in repeats:
            _, high, sub = av
            if inside_repeat and high == maxrepeat:
                return True
            if _nested_repeat(sub, constants, inside_repeat=inside_repeat or high > 1):
                return True
        elif op is constants.BRANCH:
            if inside_repeat:
                return True
            if any(_nested_repeat(branch, constants, inside_repeat=inside_repeat) for branch in av[1]):
                return True
        elif op is constants.SUBPATTERN:
            if _nested_repeat(av[3], constants, inside_repeat=inside_repeat):
                return True
        elif op in (constants.ASSERT, constants.ASSERT_NOT):
            if _nested_repeat(av[1], constants, inside_repeat=inside_repeat):
                return True
        elif op is getattr(constants, 'ATOMIC_GROUP', None) and _nested_repeat(
            av, constants, inside_repeat=inside_repeat
        ):
            return True
        elif op is constants.GROUPREF_EXISTS:
            yes, no = av[1], av[2]
            if _nested_repeat(yes, constants, inside_repeat=inside_repeat) or (
                no is not None and _nested_repeat(no, constants, inside_repeat=inside_repeat)
            ):
                return True
    return False


def compile_safe(pattern: str, *, name: str = 'pattern') -> re.Pattern:
    """Compile a user pattern, or raise ValueError when it is too long, invalid or can backtrack badly.

    Args:
        pattern: The regular expression text.
        name: What the pattern is called in error messages.

    Raises:
        ValueError: On a pattern over MAX_PATTERN_LENGTH characters, an invalid pattern, or nested/alternated repeats.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        msg = f'{name} is longer than {MAX_PATTERN_LENGTH} characters'
        raise ValueError(msg)

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        msg = f'{name} is not a valid regular expression: {e}'
        raise ValueError(msg) from e

    parser = getattr(re, '_parser', None)
    constants = getattr(re, '_constants', None)
    try:
        unsafe = (
            _unsafe_by_text(pattern)
            if parser is None or constants is None
            else _nested_repeat(parser.parse(pattern), constants, inside_repeat=False)
        )
    except (AttributeError, TypeError, ValueError):
        unsafe = _unsafe_by_text(pattern)

    if unsafe:
        msg = f'{name} nests a repeat inside a repeat or repeats an alternation, which can hang the server: {_HINT}'
        raise ValueError(msg)
    return compiled
