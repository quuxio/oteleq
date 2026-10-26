class Counter:
 total=0
 def __init__(self,start:int):
  self.value=start
  self.alias=self
  self.calls=0
 def add(self,amount:int)->int:
  self.value+=amount
  self.calls+=1
  Counter.total+=amount
  return self.value
