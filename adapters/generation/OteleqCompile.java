// JDK-owned output origins and the exact UTF-8 source characters read by javac.
import java.io.IOException;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.io.File;
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
import javax.tools.StandardLocation;
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
        return digest(text.getBytes(StandardCharsets.UTF_8));
    }
    static String digest(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(bytes));
        } catch (java.security.NoSuchAlgorithmException failure) {
            throw new IllegalStateException(failure);
        }
    }
    static class ReadClass extends ForwardingJavaFileObject<JavaFileObject> {
        final JavaFileObject original;
        final Map<String, String> reads;
        ReadClass(JavaFileObject original, Map<String, String> reads) {
            super(original); this.original = original; this.reads = reads;
        }
        @Override public InputStream openInputStream() throws IOException {
            byte[] bytes;
            try (var input = super.openInputStream()) { bytes = input.readNBytes(16 * 1024 * 1024 + 1); }
            if (bytes.length > 16 * 1024 * 1024) throw new IOException("classpath class exceeds byte budget");
            String hash = digest(bytes);
            String previous = reads.putIfAbsent(original.toUri().toString(), hash);
            if (previous != null && !previous.equals(hash)) throw new IOException("classpath class changed while compiling");
            return new ByteArrayInputStream(bytes);
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
        final Map<String, String> classReads = new LinkedHashMap<>();
        final List<String> outputs = new ArrayList<>();
        final boolean context;
        Manager(StandardJavaFileManager delegate) { this(delegate, false); }
        Manager(StandardJavaFileManager delegate, boolean context) { super(delegate); this.context = context; }
        JavaFileObject source(JavaFileObject file) {
            return file != null && file.getKind() == JavaFileObject.Kind.SOURCE
                && !(file instanceof ReadSource) ? new ReadSource(file, reads) : file;
        }
        JavaFileObject input(Location location, JavaFileObject file) {
            if (context && location == StandardLocation.CLASS_PATH && file != null
                    && file.getKind() == JavaFileObject.Kind.CLASS && !(file instanceof ReadClass))
                return new ReadClass(file, classReads);
            return source(file);
        }
        static FileObject unwrap(FileObject file) {
            if (file instanceof ReadSource source) return source.original;
            return file instanceof ReadClass binary ? binary.original : file;
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
            for (var file : super.list(location, packageName, kinds, recurse)) files.add(input(location, file));
            return files;
        }
        @Override public JavaFileObject getJavaFileForInput(Location location, String name,
                JavaFileObject.Kind kind) throws IOException {
            return input(location, super.getJavaFileForInput(location, name, kind));
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
    static class Arguments {
        final boolean context;
        final List<String> options = new ArrayList<>(List.of("-encoding", "UTF-8", "-proc:none", "-implicit:class"));
        final String[] sources;
        Arguments(String[] args) {
            context = args.length > 0 && args[0].equals("--context-v2");
            int offset = context ? 1 : 0;
            if (args.length < offset + 3) throw new IllegalArgumentException("project, output and sources are required");
            String project = args[offset++], classes = args[offset++];
            if (context) {
                int count = Integer.parseInt(args[offset++]);
                if (count < 1 || count > 256) throw new IllegalArgumentException("invalid source root count");
                options.addAll(List.of("-sourcepath", String.join(File.pathSeparator,
                    Arrays.copyOfRange(args, offset, offset + count))));
                offset += count;
                count = Integer.parseInt(args[offset++]);
                if (count < 0 || count > 256) throw new IllegalArgumentException("invalid classpath count");
                options.addAll(List.of("-classpath", count == 0 ? classes : String.join(File.pathSeparator,
                    Arrays.copyOfRange(args, offset, offset + count))));
                offset += count;
            } else options.addAll(List.of("-classpath", project));
            options.addAll(List.of("-d", classes));
            sources = Arrays.copyOfRange(args, offset, args.length);
            if (sources.length == 0) throw new IllegalArgumentException("no source units");
        }
    }
    public static void main(String[] arguments) throws Exception {
        var parsed = new Arguments(arguments);
        var compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("a complete JDK is required");
        var options = parsed.options;
        try (var standard = compiler.getStandardFileManager(null, null, StandardCharsets.UTF_8);
             var manager = new Manager(standard, parsed.context)) {
            var units = new ArrayList<JavaFileObject>();
            for (var unit : standard.getJavaFileObjects(parsed.sources))
                units.add(manager.source(unit));
            boolean success = compiler.getTask(null, manager, null, options, null, units).call();
            var reads = manager.reads.entrySet().stream()
                .map(entry -> quote(entry.getKey()) + ":" + quote(entry.getValue())).toList();
            var classReads = manager.classReads.entrySet().stream()
                .map(entry -> quote(entry.getKey()) + ":" + quote(entry.getValue())).toList();
            System.out.print("{\"schema_version\":" + (parsed.context ? 2 : 1) + ",\"success\":" + success
                + ",\"java_version\":" + quote(Runtime.version().toString())
                + ",\"options\":[" + String.join(",", options.stream().map(OteleqCompile::quote).toList())
                + "],\"source_reads_sha256\":{" + String.join(",", reads)
                + "}" + (parsed.context ? ",\"class_reads_sha256\":{" + String.join(",", classReads) + "}" : "")
                + ",\"outputs\":[" + String.join(",", manager.outputs) + "]}");
            if (!success) System.exit(1);
        }
    }
}
