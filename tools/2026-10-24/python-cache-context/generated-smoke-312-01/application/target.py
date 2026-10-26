counter=0
def workload(value:int)->int:
 global counter
 counter+=value
 return value*2+3
