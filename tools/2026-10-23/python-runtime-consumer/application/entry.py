import sys
count=0
class Counter:
    total=0
    def __init__(self,value): self.value=value

def workload(value:int)->int:
    global count
    count+=value
    Counter.total+=1
    instance=Counter(value)
    instance.value+=1
    assert instance.value==6
    return value*2

result=workload(5)
sys.stdout.buffer.write(b"raw\x00\xff|"+str(result).encode()+b"|"+str(count).encode()+b"|"+str(Counter.total).encode()+b"\n")
sys.stderr.buffer.write(b"err\x00\xfe\n")
