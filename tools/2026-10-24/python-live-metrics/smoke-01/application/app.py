created=0
global_total=0
class Counter:
 total=0
 def __init__(self,start:int):
  global created
  created+=1
  self.value=start
  self.alias=self
 def add(self,amount:int)->int:
  global global_total
  self.value+=amount
  Counter.total+=amount
  global_total+=amount
  return self.value
