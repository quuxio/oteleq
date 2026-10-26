
public final class ActionFixture {
  private int value=10;
  private static int total, getters, position;
  private static final Problem FAILURE=new Problem();
  private static final String[] ACTIONS=System.getenv("OTELEQ_FIXTURE_ACTIONS").split(",");
  private static final class Problem extends RuntimeException {
    public String getMessage(){getters++;return "changed";}
    public String toString(){getters++;return "changed";}
    public synchronized Throwable getCause(){getters++;return this;}
  }
  private int target(int seed){
    if(seed<0)throw FAILURE;
    total+=seed;value+=seed;
    return seed==0?value:target(seed-1)+seed;
  }
  private static int wrapper(ActionFixture receiver,int seed){return receiver.target(seed);}
  private static int envelope(ActionFixture receiver,int seed) throws java.io.IOException {
    rendezvous();return wrapper(receiver,seed);
  }
  private static void rendezvous() throws java.io.IOException {
    OteleqRendezvous.awaitRelease(ACTIONS[position++]);
  }
  private String state(){return "{\"value\":"+value+",\"total\":"+total+",\"getters\":"+getters+",\"position\":"+position+"}";}
  public static void main(String[] ignored) throws Exception {
    System.out.write(new byte[]{0,(byte)255,10});
    ActionFixture receiver=new ActionFixture();
    java.nio.file.Path output=java.nio.file.Path.of(System.getenv("OTELEQ_FIXTURE_OBSERVATION"));
    int[] seeds={0,2,-1,1};
    for(int seed:seeds){
      String before=receiver.state(),outcome;
      try{int value=envelope(receiver,seed);outcome="{\"kind\":\"return\",\"value\":"+value+"}";}
      catch(Problem failure){outcome="{\"kind\":\"error\",\"type\":\""+failure.getClass().getName()+"\",\"same\":"+(failure==FAILURE)+"}";}
      String row="{\"seed\":"+seed+",\"before\":"+before+",\"outcome\":"+outcome+",\"after\":"+receiver.state()+"}\n";
      java.nio.file.Files.writeString(output,row,java.nio.file.StandardOpenOption.CREATE,java.nio.file.StandardOpenOption.APPEND);
    }
    OteleqRendezvous.awaitRelease(ACTIONS[4]);
    System.err.write(new byte[]{1,(byte)254,10});
  }
}
