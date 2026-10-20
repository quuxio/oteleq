"""Keep application macros out of generated native observation code."""
from collections.abc import Iterable
import re


def identifiers(code: str, names: Iterable[str] = ()) -> set[str]:
    """Combine own-code tokens with exact compiler-declared identifier spellings."""
    result = set(re.findall(r"[A-Za-z_]\w*", code, re.ASCII))
    for name in names:
        for part in name.split('::'):
            # Clang already validated source names. Avoid Python's different
            # Unicode tables and retain Clang's supported dollar identifiers.
            if part and re.fullmatch(r'[A-Za-z_$\u0080-\U0010ffff][\w$\u0080-\U0010ffff]*', part, re.ASCII):
                result.add(part)
    return result


def undefinitions(code: str, names: Iterable[str] = (), *, preserve: Iterable[str] = ()) -> str:
    """Only explicitly owned observer macros survive the application include."""
    return ''.join('#undef ' + name + '\n' for name in sorted(identifiers(code, names) - set(preserve)))
