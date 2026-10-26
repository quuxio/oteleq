import java.io.File;
import java.util.jar.JarFile;
import java.util.zip.ZipFile;
import java.security.MessageDigest;
import java.util.HexFormat;
public class JarProbe {
 static String quote(String value){return "\""+value.replace("\\","\\\\").replace("\"","\\\"")+"\"";}
 public static void main(String[] args)throws Exception {
  int maximum=Integer.parseInt(args[1]);
  try(var jar=new JarFile(new File(args[0]),false,ZipFile.OPEN_READ,Runtime.Version.parse(args[1]))){
   var rows=new java.util.ArrayList<String>();
   for(String name:new String[]{"dep/Flags.class","fixture.properties"}){
    var entry=jar.getJarEntry(name);
    try(var input=jar.getInputStream(entry)){
     String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input.readAllBytes()));
     rows.add(quote(name)+":{\"entry\":"+quote(entry.getRealName())+",\"sha256\":"+quote(hash)+"}");
    }
   }
   System.out.print("{\"jdk_feature\":"+Runtime.version().feature()+",\"maximum\":"+maximum
    +",\"jar_version\":"+jar.getVersion().feature()+",\"multi_release\":"+jar.isMultiRelease()
    +",\"members\":{"+String.join(",",rows)+"}}");
  }
 }
}
