
public final class ActionFixture {
  private int value=10;
  private static int total, getters;
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
private static final java.lang.invoke.MethodHandle OTELEQ_HANDLE=oteleqHandle();
private static int OTELEQ_ACTION_POSITION;
private static java.lang.invoke.MethodHandle oteleqHandle(){
 try{return java.lang.invoke.MethodHandles.privateLookupIn(ActionFixture.class,java.lang.invoke.MethodHandles.lookup())
   .findVirtual(ActionFixture.class,"target",java.lang.invoke.MethodType.methodType(int.class,int.class));}
 catch(java.lang.ReflectiveOperationException failure){throw new java.lang.AssertionError("private caller handle unavailable");}
}
private static void oteleqRendezvous() throws java.io.IOException {
 java.lang.String actions=java.lang.System.getenv("OTELEQ_ACTION_IDS");
 if(actions==null)throw new java.lang.AssertionError("missing private action plan");
 OteleqRendezvous.awaitRelease(actions.split(",",-1)[OTELEQ_ACTION_POSITION++]);
}
private static int oteleqWrapper(ActionFixture receiver,int p0) throws java.lang.Throwable {return (int)OTELEQ_HANDLE.invokeExact(receiver,p0);}
private static int oteleqEnvelope(ActionFixture receiver,int p0) throws java.lang.Throwable {oteleqRendezvous();return oteleqWrapper(receiver,p0);}
  private String state(){return "{\"value\":"+value+",\"total\":"+total+",\"getters\":"+getters+",\"position\":"+OTELEQ_ACTION_POSITION+"}";}
  public static void main(String[] ignored) throws Throwable {
    System.out.write(new byte[]{0,(byte)255,10});
    ActionFixture receiver=new ActionFixture();
    java.nio.file.Path output=java.nio.file.Path.of(System.getenv("OTELEQ_FIXTURE_OBSERVATION"));
    int[] seeds={0,2,-1,1};
    for(int seed:seeds){
      String before=receiver.state(),outcome;
      try{int value=oteleqEnvelope(receiver,seed);outcome="{\"kind\":\"return\",\"value\":"+value+"}";}
      catch(Problem failure){outcome="{\"kind\":\"error\",\"type\":\""+failure.getClass().getName()+"\",\"same\":"+(failure==FAILURE)+"}";}
      String row="{\"seed\":"+seed+",\"before\":"+before+",\"outcome\":"+outcome+",\"after\":"+receiver.state()+"}\n";
      java.nio.file.Files.writeString(output,row,java.nio.file.StandardOpenOption.CREATE,java.nio.file.StandardOpenOption.APPEND);
    }
    OteleqRendezvous.awaitRelease(ACTIONS[4]);
    System.err.write(new byte[]{1,(byte)254,10});
  }
}
