"""Complete independent expectations for the existing single-call receiver corpus."""

from python_sequence_fixture import boundaries, graph


METHODS = ('add', 'identity', 'silent', 'static_only', 'fail')


def raw_observation(method: str, amount: int, active: bool) -> dict:
    """Specify the original fixture's three fields and three own-static roots."""
    assert method in METHODS and type(amount) is int and 0 <= amount <= 7
    initial = {'value': 10, 'total': 0, 'calls': 0, 'history': []}
    final = {'value': 10 if method == 'static_only' else 10 + amount + int(active and method == 'silent'),
             'total': amount + int(active and method == 'static_only'), 'calls': 0,
             'history': [amount] if method in ('add', 'identity', 'fail') else []}

    def legacy(state: dict, *, outcome: str | None = None, result: int | None = None) -> dict:
        # The independent graph model also names the sequence fixture's extra
        # scalar fields. This original source declares neither those fields nor
        # its module counter; remove them explicitly from the expected shape.
        value = graph(state, amount, outcome=outcome, result=result)
        value['roots'].pop('global:created')
        receiver = value['nodes'][value['roots']['receiver']['ref']]
        receiver['fields'] = [item for item in receiver['fields'] if item[0] not in ('calls', '_token')]
        return value

    kind = 'error' if method == 'fail' else 'identity' if method == 'identity' else 'return'
    result = final['value'] if method == 'add' else 7
    return {'before': legacy(initial),
            'outcome': {'kind': 'error' if method == 'fail' else 'return',
                        'value': legacy(final, outcome=kind, result=result)},
            'after': legacy(final)}


def check_observation(observed: dict, raw: dict, method: str, amount: int, active: bool) -> None:
    expected = raw_observation(method, amount, active)
    assert raw == expected, (method, amount, active, 'raw graph')
    assert not observed['gaps'] and 'steps' not in observed
    for name, value in boundaries(expected).items():
        assert observed[name] == value, (method, amount, active, name)
