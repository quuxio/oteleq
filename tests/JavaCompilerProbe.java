// Regression-only probes for compiler bookkeeping; no application code is loaded.
import java.io.IOException;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Set;
import javax.tools.JavaFileObject;
import javax.tools.SimpleJavaFileObject;
import javax.tools.StandardLocation;
import javax.tools.ToolProvider;

class JavaCompilerProbe {
    static void require(boolean condition) {
        if (!condition) throw new AssertionError("compiler probe failed");
    }
    static void readProbes(Path source) throws Exception {
        require(OteleqCompile.quote(null).equals("null"));
        require(OteleqCompile.quote("\"\\\n").equals("\"\\\"\\\\\\u000a\""));
        require(OteleqCompile.path(null) == null);
        var reads = new LinkedHashMap<String, String>();
        var changing = new SimpleJavaFileObject(source.toUri(), JavaFileObject.Kind.SOURCE) {
            int count;
            @Override public CharSequence getCharContent(boolean ignored) { return ++count == 1 ? "first" : "second"; }
        };
        var wrapped = new OteleqCompile.ReadSource(changing, reads);
        require(wrapped.getCharContent(false).toString().equals("first"));
        try { wrapped.getCharContent(false); throw new AssertionError("changed read passed"); }
        catch (IOException expected) { require(expected.getMessage().contains("changed")); }
        var memory = new SimpleJavaFileObject(URI.create("memory:///Source.java"), JavaFileObject.Kind.SOURCE) {
            @Override public CharSequence getCharContent(boolean ignored) { return "class Source {}"; }
        };
        require(OteleqCompile.path(memory) == null);
        try { new OteleqCompile.ReadSource(memory, new LinkedHashMap<>()).getCharContent(false); throw new AssertionError("unknown origin passed"); }
        catch (IOException expected) { require(expected.getMessage().contains("unavailable")); }
    }
    static void managerProbes(Path project, Path output, Path source) throws Exception {
        try (var standard = ToolProvider.getSystemJavaCompiler().getStandardFileManager(null, null, null);
             var manager = new OteleqCompile.Manager(standard)) {
            standard.setLocationFromPaths(StandardLocation.SOURCE_PATH, List.of(project));
            standard.setLocationFromPaths(StandardLocation.CLASS_OUTPUT, List.of(output));
            var unit = standard.getJavaFileObjects(source).iterator().next();
            var wrapped = manager.source(unit);
            require(manager.source(wrapped) == wrapped && manager.source(null) == null);
            require(manager.isSameFile(wrapped, unit));
            require(manager.contains(StandardLocation.SOURCE_PATH, wrapped));
            require(manager.inferBinaryName(StandardLocation.SOURCE_PATH, wrapped).equals("Source"));
            require(manager.getJavaFileForInput(StandardLocation.SOURCE_PATH, "Source", JavaFileObject.Kind.SOURCE) instanceof OteleqCompile.ReadSource);
            for (var candidate : manager.list(StandardLocation.SOURCE_PATH, "", Set.of(JavaFileObject.Kind.SOURCE), false))
                candidate.getCharContent(false);
            require(manager.reads.get(source.toString()).equals(OteleqCompile.digest(Files.readString(source))));
            var first = manager.getJavaFileForOutput(StandardLocation.CLASS_OUTPUT, "First", JavaFileObject.Kind.CLASS, wrapped);
            require(OteleqCompile.path(first).endsWith("First.class"));
            manager.getJavaFileForOutputForOriginatingFiles(StandardLocation.CLASS_OUTPUT, "Second", JavaFileObject.Kind.CLASS, wrapped);
            manager.getJavaFileForOutput(StandardLocation.CLASS_OUTPUT, "Third", JavaFileObject.Kind.CLASS, null);
            manager.record(first, "Other", JavaFileObject.Kind.OTHER, wrapped);
            require(manager.outputs.size() == 3);
            require(manager.source(first) == first);
        }
    }
    public static void main(String[] args) throws Exception {
        Path project = Path.of(args[0]), output = Path.of(args[1]);
        Files.createDirectories(project); Files.createDirectories(output);
        Path source = project.resolve("Source.java");
        Files.writeString(source, "class Source {static {throwIfLoaded();}static void throwIfLoaded(){throw new AssertionError(\"application loaded\");}}\n");
        readProbes(source);
        managerProbes(project, output, source);
        try { OteleqCompile.main(new String[0]); throw new AssertionError("missing arguments passed"); }
        catch (IllegalArgumentException expected) { require(expected.getMessage().contains("required")); }
        OteleqCompile.main(new String[]{project.toString(), output.toString(), source.toString()});
    }
}
