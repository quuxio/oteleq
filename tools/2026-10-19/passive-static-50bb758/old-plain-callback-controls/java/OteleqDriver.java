class OteleqDriver {
static String value(Object v){
 if(v==null)return "null";
 if(v instanceof Double x)return "double:"+Long.toHexString(Double.doubleToRawLongBits(x));
 if(v instanceof Float x)return "float:"+Integer.toHexString(Float.floatToRawIntBits(x));
 if(v instanceof Character x)return "char:"+Integer.toHexString(x.charValue());
 if(v instanceof String x){StringBuilder units=new StringBuilder("string:utf16:");for(int i=0;i<x.length();i++)units.append(String.format("%04x",(int)x.charAt(i)));return units.toString();}
 return v.getClass().getName()+":"+java.util.Base64.getEncoder().encodeToString(v.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
}
public static void main(String[] args) throws Exception {
StringBuilder s=new StringBuilder("before\n");

try{s.append("return:").append(value(App.selected())).append("\n");}catch(Exception e){s.append("error:").append(e.getClass().getName()).append(":").append(value(e.getMessage())).append("\n");}
s.append("after\n");

java.nio.file.Files.writeString(java.nio.file.Path.of(System.getenv("OTELEQ_OBSERVATION")),s.toString());
}}
