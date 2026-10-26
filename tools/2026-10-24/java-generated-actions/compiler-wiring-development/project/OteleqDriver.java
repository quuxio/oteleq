@java.lang.SuppressWarnings("removal")
class OteleqDriver {
private static final java.lang.invoke.MethodHandle OTELEQ_HANDLE=oteleqHandle();
private static int OTELEQ_ACTION_POSITION;
private static java.lang.invoke.MethodHandle oteleqHandle(){
 try{return java.lang.invoke.MethodHandles.privateLookupIn(Counter.class,java.lang.invoke.MethodHandles.lookup())
   .findVirtual(Counter.class,"run",java.lang.invoke.MethodType.methodType(Counter.class,int.class));}
 catch(java.lang.ReflectiveOperationException failure){throw new java.lang.AssertionError("private caller handle unavailable");}
}
private static void oteleqRendezvous() throws java.io.IOException {
 java.lang.String actions=java.lang.System.getenv("OTELEQ_ACTION_IDS");
 if(actions==null)throw new java.lang.AssertionError("missing private action plan");
 OteleqRendezvous.awaitRelease(actions.split(",",-1)[OTELEQ_ACTION_POSITION++]);
}
private static Counter oteleqWrapper(Counter receiver,int p0) throws java.lang.Throwable {return (Counter)OTELEQ_HANDLE.invokeExact(receiver,p0);}
private static Counter oteleqEnvelope(Counter receiver,int p0) throws java.lang.Throwable {oteleqRendezvous();return oteleqWrapper(receiver,p0);}

static OteleqGraph observer() throws java.lang.Exception {
return new OteleqGraph(new java.lang.Class<?>[]{Counter.class},new java.lang.String[][]{new java.lang.String[]{"value"}},new java.lang.Class<?>[][]{new java.lang.Class<?>[]{int.class}},new int[][]{new int[]{2}});
}
static java.lang.String graph(Counter receiver,java.lang.Object[] arguments,java.lang.Object result,java.lang.Exception failure,boolean outcome) throws java.lang.Exception {
OteleqGraph observer=observer();
java.util.ArrayList<java.lang.String> names=new java.util.ArrayList<>(java.util.List.of("receiver","argument:0"));
java.util.ArrayList<java.lang.Object> values=new java.util.ArrayList<>(java.util.Arrays.asList(receiver,arguments[0]));
java.util.ArrayList<java.lang.Class<?>> types=new java.util.ArrayList<>(java.util.List.of(Counter.class,int.class));
if(outcome){names.add(failure==null?"result":"error");values.add(failure==null?result:failure);types.add(failure==null?Counter.class:java.lang.Exception.class);}
return observer.graph(names.toArray(new java.lang.String[0]),values.toArray(),types.toArray(new java.lang.Class<?>[0]));
}
static java.lang.String[] call(Counter receiver,java.lang.Object[] arguments,java.lang.reflect.Method target) throws java.lang.Throwable {
java.lang.String before=graph(receiver,arguments,null,null,false);
java.lang.Object result=null;java.lang.Exception failure=null;
try{result=oteleqEnvelope(receiver,(int)arguments[0]);}catch(java.lang.Throwable caught){
if(!(caught instanceof java.lang.Exception))throw new java.lang.AssertionError("target throwable requires another codec");
failure=(java.lang.Exception)caught;}
java.lang.String outcome=graph(receiver,arguments,result,failure,true);
java.lang.String after=graph(receiver,arguments,null,null,false);
return new java.lang.String[]{before,"{\"kind\":\""+(failure==null?"return":"error")+"\",\"value\":"+outcome+"}",after};
}
static java.lang.String boundaries(java.lang.String[] capture){
return "\"before\":"+capture[0]+",\"outcome\":"+capture[1]+",\"after\":"+capture[2];
}
public static void main(java.lang.String[] ignored) throws java.lang.Throwable {
if(java.lang.System.getSecurityManager()!=null)throw new java.lang.AssertionError("custom security manager requires a fixture");
java.lang.reflect.Method target=Counter.class.getDeclaredMethod("run",int.class);
if(java.lang.reflect.Modifier.isStatic(target.getModifiers()) || target.isSynthetic() || target.isBridge() || target.getReturnType()!=Counter.class || !target.trySetAccessible())throw new java.lang.AssertionError("receiver method binding unavailable");
java.lang.Object constructed;
// Construction is fixture setup. Never let JVM failure reporting format an application cause.
try{java.lang.reflect.Method factory=Counter.class.getDeclaredMethod("make",int.class);
if(!java.lang.reflect.Modifier.isStatic(factory.getModifiers()) || !factory.trySetAccessible())throw new java.lang.AssertionError("receiver factory binding unavailable");
constructed=factory.invoke(null,new java.lang.Object[]{10});}catch(java.lang.Throwable failure){throw new java.lang.AssertionError("receiver construction failed");}
if(constructed==null || constructed.getClass()!=Counter.class)throw new java.lang.AssertionError("receiver factory returned the wrong class");
Counter receiver=(Counter)constructed;
java.lang.String capture="{\"java_receiver_schema_version\":1,"+boundaries(call(receiver,new java.lang.Object[]{7},target))+"}";
java.nio.file.Files.writeString(java.nio.file.Path.of(java.lang.System.getenv("OTELEQ_OBSERVATION")),capture);
OteleqRendezvous.awaitRelease(java.lang.System.getenv("OTELEQ_ACTION_IDS").split(",",-1)[OTELEQ_ACTION_POSITION]);
}
}
// Generated observer support. No application formatting, getters or equality calls.
final class OteleqGraph {
    private static final int MAX_BYTES = 262144;
    private static final java.util.Set<java.lang.Class<?>> ERRORS = java.util.Set.of(
        java.lang.Exception.class, java.lang.RuntimeException.class, java.lang.IllegalArgumentException.class,
        java.lang.IllegalStateException.class, java.lang.NullPointerException.class, java.lang.ArithmeticException.class,
        java.lang.IndexOutOfBoundsException.class, java.lang.ArrayIndexOutOfBoundsException.class,
        java.lang.StringIndexOutOfBoundsException.class, java.lang.UnsupportedOperationException.class,
        java.lang.ClassCastException.class, java.lang.NumberFormatException.class);
    private final java.util.IdentityHashMap<java.lang.Object, java.lang.Integer> seen = new java.util.IdentityHashMap<>();
    private final java.util.ArrayList<java.lang.String> nodes = new java.util.ArrayList<>();
    private final java.util.IdentityHashMap<java.lang.Class<?>, java.lang.reflect.Field[]> fields = new java.util.IdentityHashMap<>();
    private int bytes;
    private boolean captured;

    @java.lang.SuppressWarnings("removal")
    OteleqGraph(java.lang.Class<?>[] classes, java.lang.String[][] names, java.lang.Class<?>[][] types, int[][] modifiers) throws java.lang.Exception {
        if (java.lang.System.getSecurityManager() != null) throw new java.lang.IllegalArgumentException("custom security manager requires a fixture");
        if (classes.length > 64 || classes.length != names.length || classes.length != types.length || classes.length != modifiers.length)
            throw new java.lang.IllegalArgumentException("invalid source field contract");
        for (int i = 0; i < classes.length; i++) {
            java.lang.Class<?> kind = classes[i];
            if (fields.containsKey(kind) || kind.getSuperclass() != java.lang.Object.class || kind.getInterfaces().length != 0 || kind.isRecord()
                    || kind.isEnum() || kind.isAnonymousClass() || kind.isLocalClass() || kind.isHidden()
                    || kind.getEnclosingClass() != null || kind.isSynthetic())
                throw new java.lang.IllegalArgumentException("unsupported source class storage");
            java.lang.reflect.Field[] actual = kind.getDeclaredFields();
            if (actual.length > 256 || actual.length != names[i].length || actual.length != types[i].length || actual.length != modifiers[i].length)
                throw new java.lang.IllegalArgumentException("source fields changed");
            java.lang.reflect.Field[] ordered = new java.lang.reflect.Field[actual.length];
            java.util.HashSet<java.lang.String> unique = new java.util.HashSet<>();
            for (int j = 0; j < ordered.length; j++) {
                if (!unique.add(names[i][j])) throw new java.lang.IllegalArgumentException("duplicate source field");
                java.lang.reflect.Field field = kind.getDeclaredField(names[i][j]);
                if (field.isSynthetic() || field.getType() != types[i][j] || field.getModifiers() != modifiers[i][j]
                        || !field.trySetAccessible()) throw new java.lang.IllegalArgumentException("source field binding unavailable");
                ordered[j] = field;
            }
            fields.put(kind, ordered);
        }
    }

    static java.lang.String quote(java.lang.String text) {
        if (text.length() > MAX_BYTES) throw new java.lang.IllegalArgumentException("string observation budget exceeded");
        java.lang.StringBuilder result = new java.lang.StringBuilder("\"");
        for (int i = 0; i < text.length(); i++) {
            char unit = text.charAt(i);
            if (unit == '"' || unit == '\\') result.append('\\').append(unit);
            else if (unit < 32 || unit > 126) result.append("\\u").append(hex(unit, 4));
            else result.append(unit);
            if (result.length() > MAX_BYTES) throw new java.lang.IllegalArgumentException("encoded observation budget exceeded");
        }
        return result.append('"').toString();
    }

    private static java.lang.String hex(long value, int width) {
        java.lang.String text = java.lang.Long.toHexString(value);
        return "0".repeat(width - text.length()) + text;
    }

    private java.lang.String retain(java.lang.String text) {
        bytes += text.length();
        if (bytes > MAX_BYTES) throw new java.lang.IllegalArgumentException("encoded observation budget exceeded");
        return text;
    }

    private static java.lang.String integer(java.lang.String kind, long number, int bits, boolean signed) {
        return "{\"kind\":\"integer\",\"type\":" + quote("java." + kind) + ",\"value\":"
                + quote(java.lang.Long.toString(number)) + ",\"bits\":" + bits + ",\"signed\":" + signed + "}";
    }

    private static java.lang.String scalar(java.lang.Object value, java.lang.Class<?> kind) {
        if (kind == boolean.class && value.getClass() == java.lang.Boolean.class)
            return "{\"kind\":\"boolean\",\"type\":\"java.boolean\",\"value\":" + ((java.lang.Boolean) value).booleanValue() + "}";
        if (kind == byte.class && value.getClass() == java.lang.Byte.class) return integer("byte", ((java.lang.Byte) value).byteValue(), 8, true);
        if (kind == short.class && value.getClass() == java.lang.Short.class) return integer("short", ((java.lang.Short) value).shortValue(), 16, true);
        if (kind == int.class && value.getClass() == java.lang.Integer.class) return integer("int", ((java.lang.Integer) value).intValue(), 32, true);
        if (kind == long.class && value.getClass() == java.lang.Long.class) return integer("long", ((java.lang.Long) value).longValue(), 64, true);
        if (kind == char.class && value.getClass() == java.lang.Character.class) return integer("char", ((java.lang.Character) value).charValue(), 16, false);
        if (kind == float.class && value.getClass() == java.lang.Float.class)
            return "{\"kind\":\"float\",\"type\":\"java.float\",\"bits\":" + quote(hex(java.lang.Integer.toUnsignedLong(java.lang.Float.floatToRawIntBits(((java.lang.Float) value).floatValue())), 8)) + "}";
        if (kind == double.class && value.getClass() == java.lang.Double.class)
            return "{\"kind\":\"float\",\"type\":\"java.double\",\"bits\":" + quote(hex(java.lang.Double.doubleToRawLongBits(((java.lang.Double) value).doubleValue()), 16)) + "}";
        if (kind == java.lang.String.class && value.getClass() == java.lang.String.class) {
            java.lang.String text = (java.lang.String) value;
            if (text.length() > 65536) throw new java.lang.IllegalArgumentException("string observation budget exceeded");
            java.lang.StringBuilder units = new java.lang.StringBuilder();
            for (int i = 0; i < text.length(); i++) units.append(hex(text.charAt(i), 4));
            return "{\"kind\":\"string\",\"type\":\"java.lang.String\",\"encoding\":\"utf16_be\",\"value\":" + quote(units.toString()) + "}";
        }
        throw new java.lang.IllegalArgumentException("unsupported primitive observation");
    }

    private static java.lang.Class<?> unboxed(java.lang.Class<?> kind) {
        if (kind == java.lang.Boolean.class) return boolean.class;
        if (kind == java.lang.Byte.class) return byte.class;
        if (kind == java.lang.Short.class) return short.class;
        if (kind == java.lang.Integer.class) return int.class;
        if (kind == java.lang.Long.class) return long.class;
        if (kind == java.lang.Character.class) return char.class;
        if (kind == java.lang.Float.class) return float.class;
        if (kind == java.lang.Double.class) return double.class;
        return kind == java.lang.String.class ? java.lang.String.class : null;
    }

    java.lang.Object staticValue(java.lang.Class<?> owner, java.lang.String name) throws java.lang.Exception {
        java.lang.reflect.Field[] declared = fields.get(owner);
        if (declared == null) throw new java.lang.IllegalArgumentException("static owner is not source-bound");
        for (java.lang.reflect.Field field : declared) {
            if (field.getName().equals(name) && java.lang.reflect.Modifier.isStatic(field.getModifiers()))
                return field.get(null);
        }
        throw new java.lang.IllegalArgumentException("static root is not source-bound");
    }

    java.lang.String value(java.lang.Object value, java.lang.Class<?> declared, int depth) throws java.lang.Exception {
        if (declared == void.class) {
            if (value != null) throw new java.lang.IllegalArgumentException("nonempty void observation");
            return retain("{\"kind\":\"undefined\"}");
        }
        if (value == null) {
            if (declared.isPrimitive()) throw new java.lang.IllegalArgumentException("null primitive observation");
            return retain("{\"kind\":\"null\"}");
        }
        if (declared.isPrimitive()) return retain(scalar(value, declared));
        if (!declared.isInstance(value)) throw new java.lang.IllegalArgumentException("declared reference type changed");
        java.lang.Integer prior = seen.get(value);
        if (prior != null) return retain("{\"kind\":\"reference\",\"node_id\":\"n" + prior + "\"}");
        if (depth > 32 || nodes.size() >= 512) throw new java.lang.IllegalArgumentException("graph observation budget exceeded");
        java.lang.Class<?> kind = value.getClass();
        java.lang.Class<?> primitive = unboxed(kind);
        if (primitive == null && !kind.isArray() && kind != java.lang.Object.class && !fields.containsKey(kind) && !ERRORS.contains(kind))
            throw new java.lang.IllegalArgumentException("opaque object storage requires a fixture");
        int id = nodes.size(); seen.put(value, id); nodes.add(null);
        java.util.ArrayList<java.lang.String> contents = new java.util.ArrayList<>();
        if (ERRORS.contains(kind)) contents.add(retain(quote("message") + ":")
                + value(((java.lang.Exception) value).getMessage(), java.lang.String.class, depth + 1));
        else if (primitive != null) contents.add(retain(quote("value") + ":") + retain(scalar(value, primitive)));
        else if (kind.isArray()) {
            int length = java.lang.reflect.Array.getLength(value);
            if (length > 4096) throw new java.lang.IllegalArgumentException("array observation budget exceeded");
            contents.add(retain(quote("length") + ":") + retain(integer("int", length, 32, true)));
            for (int i = 0; i < length; i++) contents.add(retain(quote("item:" + i) + ":") + value(java.lang.reflect.Array.get(value, i), kind.getComponentType(), depth + 1));
        } else if (kind != java.lang.Object.class) {
            for (java.lang.reflect.Field field : fields.get(kind)) {
                if (!java.lang.reflect.Modifier.isStatic(field.getModifiers()))
                    contents.add(retain(quote(field.getName()) + ":") + value(field.get(value), field.getType(), depth + 1));
            }
        }
        java.lang.String label = ERRORS.contains(kind) ? kind.getName() : "java.object:" + kind.getName();
        java.lang.String node = retain("{\"id\":\"n" + id + "\",\"type\":" + quote(label) + ",\"fields\":{") + java.lang.String.join(",", contents) + "}}";
        nodes.set(id, node);
        return retain("{\"kind\":\"reference\",\"node_id\":\"n" + id + "\"}");
    }

    java.lang.String graph(java.lang.String[] names, java.lang.Object[] values, java.lang.Class<?>[] types) throws java.lang.Exception {
        if (names.length != values.length || names.length != types.length || names.length > 512)
            throw new java.lang.IllegalArgumentException("invalid observation roots");
        if (captured) throw new java.lang.IllegalArgumentException("observer cannot reuse an earlier boundary");
        captured = true;
        java.util.HashSet<java.lang.String> unique = new java.util.HashSet<>();
        java.util.ArrayList<java.lang.String> roots = new java.util.ArrayList<>();
        for (int i = 0; i < names.length; i++) {
            if (!unique.add(names[i])) throw new java.lang.IllegalArgumentException("duplicate observation root");
            roots.add(retain(quote(names[i]) + ":") + value(values[i], types[i], 0));
        }
        java.lang.String result = "{\"roots\":{" + java.lang.String.join(",", roots) + "},\"nodes\":[" + java.lang.String.join(",", nodes) + "]}";
        if (result.length() > MAX_BYTES) throw new java.lang.IllegalArgumentException("encoded observation budget exceeded");
        return result;
    }
}
