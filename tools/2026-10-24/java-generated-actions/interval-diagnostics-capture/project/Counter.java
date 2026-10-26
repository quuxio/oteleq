class Counter {
private int value;private static int total;private Counter self=this;
private Counter(int initial){value=initial;}
private static Counter make(int initial){return new Counter(initial);}
private Counter run(int amount){

total++;
if(amount<0)throw new IllegalStateException("negative");
value+=amount;
if(amount>0)run(amount-1);
return this;
}
}
