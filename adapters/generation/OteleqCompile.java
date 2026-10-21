// JDK-owned output origins and the exact UTF-8 source characters read by javac.
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.tools.FileObject;
import javax.tools.ForwardingJavaFileManager;
import javax.tools.ForwardingJavaFileObject;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

class OteleqCompile {
    static String quote(String value) {
        if (value == null) return "null";
        var result = new StringBuilder("\"");
        for (char unit : value.toCharArray()) {
            if (unit == '\\' || unit == '"') result.append('\\').append(unit);
            else if (unit < 32) result.append(String.format("\\u%04x", (int) unit));
            else result.append(unit);
        }
        return result.append('"').toString();
    }
    static String path(FileObject file) {
        return file == null || !file.toUri().getScheme().equals("file") ? null
            : Path.of(file.toUri()).toAbsolutePath().normalize().toString();
    }
    static String digest(String text) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException failure) {
            throw new IllegalStateException(failure);
        }
    }
    static class ReadSource extends ForwardingJavaFileObject<JavaFileObject> {
        final JavaFileObject original;
        final Map<String, String> reads;
        ReadSource(JavaFileObject original, Map<String, String> reads) {
            super(original); this.original = original; this.reads = reads;
        }
        @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) throws IOException {
            CharSequence content = super.getCharContent(ignoreEncodingErrors);
            String source = path(original);
            String hash = digest(content.toString());
            String previous = reads.putIfAbsent(source, hash);
            if (source == null || previous != null && !previous.equals(hash))
                throw new IOException("source origin is unavailable or changed while compiling");
            return content;
        }
    }
    static class Manager extends ForwardingJavaFileManager<StandardJavaFileManager> {
        final Map<String, String> reads = new LinkedHashMap<>();
        final List<String> outputs = new ArrayList<>();
        Manager(StandardJavaFileManager delegate) { super(delegate); }
        JavaFileObject source(JavaFileObject file) {
            return file != null && file.getKind() == JavaFileObject.Kind.SOURCE
                && !(file instanceof ReadSource) ? new ReadSource(file, reads) : file;
        }
        static FileObject unwrap(FileObject file) {
            return file instanceof ReadSource source ? source.original : file;
        }
        @Override public String inferBinaryName(Location location, JavaFileObject file) {
            return super.inferBinaryName(location, (JavaFileObject) unwrap(file));
        }
        @Override public boolean isSameFile(FileObject left, FileObject right) {
            return super.isSameFile(unwrap(left), unwrap(right));
        }
        @Override public boolean contains(Location location, FileObject file) throws IOException {
            return super.contains(location, unwrap(file));
        }
        @Override public Iterable<JavaFileObject> list(Location location, String packageName,
                Set<JavaFileObject.Kind> kinds, boolean recurse) throws IOException {
            var files = new ArrayList<JavaFileObject>();
            for (var file : super.list(location, packageName, kinds, recurse)) files.add(source(file));
            return files;
        }
        @Override public JavaFileObject getJavaFileForInput(Location location, String name,
                JavaFileObject.Kind kind) throws IOException {
            return source(super.getJavaFileForInput(location, name, kind));
        }
        JavaFileObject record(JavaFileObject output, String name, JavaFileObject.Kind kind,
                FileObject... origins) {
            if (kind == JavaFileObject.Kind.CLASS) {
                var paths = Arrays.stream(origins).map(OteleqCompile::path).map(OteleqCompile::quote).toList();
                outputs.add("{\"class\":" + quote(name) + ",\"output\":" + quote(path(output))
                    + ",\"origins\":[" + String.join(",", paths) + "]}");
            }
            return output;
        }
        @Override public JavaFileObject getJavaFileForOutput(Location location, String name,
                JavaFileObject.Kind kind, FileObject sibling) throws IOException {
            var output = super.getJavaFileForOutput(location, name, kind, unwrap(sibling));
            return record(output, name, kind, sibling == null ? new FileObject[0] : new FileObject[]{sibling});
        }
        @Override public JavaFileObject getJavaFileForOutputForOriginatingFiles(Location location,
                String name, JavaFileObject.Kind kind, FileObject... origins) throws IOException {
            FileObject[] originals = Arrays.stream(origins).map(Manager::unwrap).toArray(FileObject[]::new);
            // Bypass ForwardingJavaFileManager's fallback to our older override.
            var output = fileManager.getJavaFileForOutputForOriginatingFiles(location, name, kind, originals);
            return record(output, name, kind, origins);
        }
    }
    public static void main(String[] arguments) throws Exception {
        if (arguments.length < 3) throw new IllegalArgumentException("project, output and sources are required");
        var compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("a complete JDK is required");
        var options = List.of("-encoding", "UTF-8", "-proc:none", "-implicit:class",
            "-classpath", arguments[0], "-d", arguments[1]);
        try (var standard = compiler.getStandardFileManager(null, null, StandardCharsets.UTF_8);
             var manager = new Manager(standard)) {
            var units = new ArrayList<JavaFileObject>();
            for (var unit : standard.getJavaFileObjects(Arrays.copyOfRange(arguments, 2, arguments.length)))
                units.add(manager.source(unit));
            boolean success = compiler.getTask(null, manager, null, options, null, units).call();
            var reads = manager.reads.entrySet().stream()
                .map(entry -> quote(entry.getKey()) + ":" + quote(entry.getValue())).toList();
            System.out.print("{\"schema_version\":1,\"success\":" + success
                + ",\"java_version\":" + quote(Runtime.version().toString())
                + ",\"options\":[" + String.join(",", options.stream().map(OteleqCompile::quote).toList())
                + "],\"source_reads_sha256\":{" + String.join(",", reads)
                + "},\"outputs\":[" + String.join(",", manager.outputs) + "]}");
            if (!success) System.exit(1);
        }
    }
}
