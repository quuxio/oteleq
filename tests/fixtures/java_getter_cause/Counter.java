class Counter {
 private int value;
 private static int total;
 Counter self=this;
 Object[] shared=new Object[]{this,null};
 private Counter(int start){value=start;shared[1]=shared;}
 void callback(){value++;}
 int run(int amount){value+=amount;total+=amount;throw new RuntimeException("outer",new Callback(this));}
}
class Callback extends RuntimeException {
 private final Counter owner;
 Callback(Counter value){owner=value;}
 public String getMessage(){owner.callback();return "inner";}
}
