import _io, json, sys
from importlib._bootstrap_external import FileLoader
events = []
def profile(frame, event, function):
    if event == "c_call" and getattr(function, "__name__", None) == "read":
        file = getattr(function, "__self__", None)
        if type(file) is _io.FileIO:
            expected = _io.FileIO.read.__get__(file, _io.FileIO)
            events.append([function == expected, hash(function) == hash(expected)])
sys.setprofile(profile)
result = FileLoader("data", "data.bin").get_data("data.bin")
sys.setprofile(None)
print(json.dumps({"content": result.hex(), "events": events}, sort_keys=True))
