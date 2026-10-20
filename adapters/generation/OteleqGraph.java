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
