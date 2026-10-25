"""Trusted harness SOURCE for the isolated runner. Never executed by this module."""
import json

from server.lessons.contracts import GradingKey
from server.providers.base import GenerationError


HARNESS = r'''
import sys, json, io, contextlib
_spec = json.loads(SPEC_LITERAL)
_events = []
_last = [None]
_names = set()
for _state in _spec['trace']:
    _names.update(_state['variables'])
    if _state['array_name']: _names.add(_state['array_name'])
    if _state['index_variable']: _names.add(_state['index_variable'])
def _trace(frame, event, arg):
    if frame.f_code.co_filename != '<teaching-example>': return _trace
    if event in ('line', 'return'):
        if _last[0] is not None:
            if len(_events) > 500: raise RuntimeError('Teaching trace exceeds its bounded event budget')
            _values = {}
            _arrays = {}
            for _name in _names:
                if _name in frame.f_locals:
                    _value = frame.f_locals[_name]
                    if type(_value) in (int, float, bool, str, type(None), list, tuple):
                        _values[_name] = repr(_value)
                        if type(_value) in (list, tuple) and len(_value) <= 10:
                            _arrays[_name] = [repr(x) for x in _value]
            _events.append((_last[0], _values, _arrays))
        _last[0] = frame.f_lineno if event == 'line' else None
    return _trace
_namespace = {'__name__': '__main__'}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        sys.settrace(_trace)
        exec(compile('\n'.join(_spec['code_lines']), '<teaching-example>', 'exec'), _namespace)
        sys.settrace(None)
finally:
    sys.settrace(None)
_cursor = 0
_ok = True
for _wanted in _spec['trace']:
    _matched = False
    while _cursor < len(_events):
        _line, _values, _arrays = _events[_cursor]
        _cursor += 1
        if _line != _wanted['line']: continue
        if any(_values.get(k) != v for k, v in _wanted['variables'].items()): continue
        if _wanted['array'] and _arrays.get(_wanted['array_name']) != _wanted['array']: continue
        if _wanted['active_index'] is not None and _values.get(_wanted['index_variable']) != repr(_wanted['active_index']): continue
        _matched = True
        break
    if not _matched:
        _ok = False
        break
print('TRACE_OK' if _ok else 'TRACE_MISMATCH')
'''


def trace_harness(visual):
    spec = visual.model_dump()
    for state in spec["trace"]:
        if state["array"] and not state["array_name"]:
            raise GenerationError("TRACE_NEEDS_REVIEW", "Array traces must identify their actual Python list variable.")
        if state["active_index"] is not None and not state["index_variable"]:
            raise GenerationError("TRACE_NEEDS_REVIEW", "Array highlights must identify the program's actual index variable.")
    return HARNESS.replace("SPEC_LITERAL", repr(json.dumps(spec)))


def trace_key():
    return GradingKey(tests=[{"stdin": "", "expected": "TRACE_OK\n", "category": "example-trace", "essential": True}],
                      hints=["Check the source example."], explanation="The illustrated states must occur in this program in the depicted order.").model_dump()
