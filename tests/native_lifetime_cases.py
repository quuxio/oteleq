"""Independent closed expectations for the maintained native lifetime corpus."""

from native_prepared_otlp import require


def expected(language: str, mode: str) -> dict:
    """Declare zero, completed, censored or caught C++ unwinding before launch."""
    require(type(language) is str and language in ('c', 'cpp') and type(mode) is str
            and mode in ('completed', 'zero', 'censored', 'unwind')
            and (mode != 'unwind' or language == 'cpp'), 'foreign native lifetime corpus mode')
    admitted = int(mode != 'zero')
    complete = mode in ('completed', 'unwind')
    release = 'destructor_entry' if language == 'cpp' else 'free_entry'
    boundary = 'shutdown_censored' if mode == 'censored' else release
    observations = [] if not admitted else [{
        'type_usr': 'c:@S@Item', 'name': 'Item', 'creation_path': [0],
        'release_path': [0] if complete else None, 'complete': complete,
        'exception_exit': mode == 'unwind' if language == 'cpp' and complete else None}]
    terminal = 'completed' if complete else 'incomplete'
    instruments = () if not admitted else tuple('otelc.lifetime.' + name
                                               for name in ('admitted', terminal, 'duration', 'live'))
    return {'observations': observations, 'admitted': admitted, 'completed': int(complete),
            'censored': int(mode == 'censored'), 'spans': 1 + admitted,
            'arguments': (0,) if mode == 'zero' else (5,),
            'release_boundary': release, 'boundary': boundary, 'instruments': instruments}
