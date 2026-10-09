total = 0
state = {"items": []}
def add(x: int) -> int:
    global total
    total += x
    state["items"].append(x)
    return x+1
