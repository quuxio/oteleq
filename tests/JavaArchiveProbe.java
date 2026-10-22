// Regression-only coverage for the selected-JDK archive resolver.
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

class JavaArchiveProbe {
    static void require(boolean condition) {
        if (!condition) throw new AssertionError("archive probe failed");
    }
    static Path jar(Path folder, String name, Map<String, byte[]> entries) throws Exception {
        Path output = folder.resolve(name + ".jar");
        try (var stream = new ZipOutputStream(Files.newOutputStream(output))) {
            for (var entry : entries.entrySet()) {
                stream.putNextEntry(new ZipEntry(entry.getKey()));
                stream.write(entry.getValue());
                stream.closeEntry();
            }
        }
        return output;
    }
    static void refused(String[] arguments) throws Exception {
        try { OteleqArchives.main(arguments); throw new AssertionError("invalid arguments passed"); }
        catch (IllegalArgumentException expected) { require(!expected.getMessage().isEmpty()); }
    }
    public static void main(String[] arguments) throws Exception {
        Path folder = Files.createDirectory(Path.of(arguments[0]));
        require(OteleqArchives.quote("\"\\\n").equals("\"\\\"\\\\\\u000a\""));
        require(OteleqArchives.digest(new ByteArrayInputStream(new byte[0]))
            .equals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
        try { OteleqArchives.digest(new ByteArrayInputStream(new byte[3]), 2); throw new AssertionError("byte budget passed"); }
        catch (IOException expected) { require(expected.getMessage().contains("byte budget")); }
        var entries = new LinkedHashMap<String, byte[]>();
        entries.put("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nMulti-Release: true\r\n\r\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        entries.put("ordinary/", new byte[0]);
        entries.put("ordinary/Value.class", new byte[]{8});
        entries.put("META-INF/versions/21/ordinary/Value.class", new byte[]{21});
        entries.put("ordinary/package-info.class", new byte[]{1});
        entries.put("module-info.class", new byte[]{2});
        entries.put("resource.txt", new byte[]{3});
        Path active = jar(folder, "active", entries);
        String selected = OteleqArchives.archive(active, 2);
        require(selected.contains("\"classpath_index\":2") && selected.contains("\"multi_release\":true"));
        require(selected.contains("META-INF/versions/21/ordinary/Value.class")
            && selected.contains("ordinary.package-info") && !selected.contains("module-info"));
        OteleqArchives.main(new String[]{folder.toString(), active.toString()});
        refused(new String[0]);
        refused(new String[]{active.toString(), active.toString()});
        String[] excessive = new String[257];
        Arrays.fill(excessive, active.toString());
        refused(excessive);
        for (String key : new String[]{"jdk.util.jar.version", "jdk.util.jar.enableMultiRelease"}) {
            System.setProperty(key, "8");
            try { refused(new String[]{active.toString()}); }
            finally { System.clearProperty(key); }
        }
        for (String kind : new String[]{"index", "classpath", "malformed", "oversized"}) {
            Map<String, byte[]> invalid = switch (kind) {
                case "index" -> Map.of("META-INF/INDEX.LIST", new byte[0]);
                case "classpath" -> Map.of("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nClass-Path: elsewhere.jar\n\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
                case "malformed" -> Map.of("META-INF/MANIFEST.MF", "not a manifest\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
                default -> Map.of("Big.class", new byte[16 * 1024 * 1024 + 1]);
            };
            try { OteleqArchives.archive(jar(folder, kind, invalid), 0); throw new AssertionError("unsafe archive passed"); }
            catch (IOException expected) { require(!expected.getMessage().isEmpty()); }
        }
        Path plain = jar(folder, "plain", Map.of("Plain.class", new byte[]{8}));
        require(OteleqArchives.archive(plain, 0).contains("\"multi_release\":false"));
    }
}
