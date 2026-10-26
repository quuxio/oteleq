import builtins
import _frozen_importlib_external as external
original = external.__dict__.pop("SourceLoader")
class Key:
    def __hash__(self): return hash("SourceLoader")
    def __eq__(self, other):
        builtins.origin_callback_count += 1
        return type(other) is str and other == "SourceLoader"
external.__dict__[Key()] = original
builtins.origin_callback_count = 0
