counter=0
def selected(value:int)->int:
    global counter
    counter+=value+1
    return counter
selected(0)
def replacement(value:int)->int:
    return counter
globals().update(selected=replacement)
