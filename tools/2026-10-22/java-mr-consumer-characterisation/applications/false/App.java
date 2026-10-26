import dep.Flags;
public class App {
 public static void main(String[] args)throws Exception {
  java.util.Properties properties=new java.util.Properties();
  try(java.io.InputStream input=App.class.getResourceAsStream("/fixture.properties")){properties.load(input);}
  System.out.println(Flags.INLINE+":"+Flags.value()+":"+properties.getProperty("value"));
 }
}
