// Selected-JDK runtime archive evidence; never load an application class.
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.jar.Attributes;
import java.util.jar.JarFile;
import java.util.zip.ZipFile;

class OteleqArchives {
    private OteleqArchives() {}

    static String quote(String value) {
        var result = new StringBuilder("\"");
        for (char unit : value.toCharArray()) {
            if (unit == '\\' || unit == '"') result.append('\\').append(unit);
            else if (unit < 32) result.append(String.format(java.util.Locale.ROOT, "\\u%04x", (int) unit));
            else result.append(unit);
        }
        return result.append('"').toString();
    }

    static String digest(InputStream input) throws Exception {
        return digest(input, 128L * 1024 * 1024);
    }

    static String digest(InputStream input, long maximum) throws Exception {
        var hash = MessageDigest.getInstance("SHA-256");
        try (input) {
            byte[] block = new byte[8192];
            long size = 0;
            int count;
            while ((count = input.read(block)) != -1) {
                size += count;
                if (size > maximum) throw new IOException("archive input exceeds byte budget");
                hash.update(block, 0, count);
            }
        }
        return HexFormat.of().formatHex(hash.digest());
    }

    static String archive(Path path, int index) throws Exception {
        String hash = digest(Files.newInputStream(path));
        List<String> classes;
        boolean multiRelease;
        try (var jar = new JarFile(path.toFile(), true, ZipFile.OPEN_READ, Runtime.version())) {
            var names = new HashSet<String>();
            for (var entries = jar.entries(); entries.hasMoreElements();) {
                var entry = entries.nextElement();
                if (!names.add(entry.getName()) || names.size() > 20000)
                    throw new IOException("duplicate or excessive JAR members");
                if (entry.getName().equalsIgnoreCase("META-INF/INDEX.LIST"))
                    throw new IOException("implicit JAR indexes are unsupported");
            }
            var manifest = jar.getManifest();
            if (manifest != null && manifest.getMainAttributes().getValue(Attributes.Name.CLASS_PATH) != null)
                throw new IOException("implicit JAR Class-Path is unsupported");
            multiRelease = jar.isMultiRelease();
            classes = classes(jar);
        }
        if (!hash.equals(digest(Files.newInputStream(path)))) throw new IOException("JAR changed during resolution");
        return "{\"classpath_index\":" + index + ",\"path\":" + quote(path.toString())
            + ",\"sha256\":" + quote(hash) + ",\"multi_release\":" + multiRelease
            + ",\"classes\":{" + String.join(",", classes) + "}}";
    }

    static List<String> classes(JarFile jar) throws Exception {
        var result = new ArrayList<String>();
        try (var stream = jar.versionedStream()) {
            for (var entries = stream.iterator(); entries.hasNext();) {
                var entry = entries.next();
                String name = entry.getName();
                if (entry.isDirectory() || !name.endsWith(".class")
                        || name.startsWith("META-INF/") || name.equals("module-info.class")) continue;
                if (entry.getSize() > 16 * 1024 * 1024)
                    throw new IOException("runtime class exceeds byte budget");
                String binary = name.substring(0, name.length() - 6).replace('/', '.');
                result.add(quote(binary) + ":{\"entry\":" + quote(entry.getRealName())
                    + ",\"sha256\":" + quote(digest(jar.getInputStream(entry), 16L * 1024 * 1024)) + "}");
            }
        }
        return result;
    }

    public static void main(String[] arguments) throws Exception {
        if (System.getProperty("jdk.util.jar.version") != null
                || System.getProperty("jdk.util.jar.enableMultiRelease") != null)
            throw new IllegalArgumentException("runtime archives require default JDK selection properties");
        if (arguments.length == 0 || arguments.length > 256)
            throw new IllegalArgumentException("expected a bounded explicit ordered classpath");
        var archives = new ArrayList<String>();
        var paths = new HashSet<Path>();
        for (int index = 0; index < arguments.length; index++) {
            Path path = Path.of(arguments[index]).toRealPath();
            if (!paths.add(path)) throw new IllegalArgumentException("duplicate classpath location");
            if (!Files.isDirectory(path)) archives.add(archive(path, index));
        }
        System.out.print("{\"schema_version\":1,\"profile\":\"java-runtime-archives-v1\",\"jdk_feature\":"
            + Runtime.version().feature() + ",\"archives\":[" + String.join(",", archives) + "]}");
    }
}
