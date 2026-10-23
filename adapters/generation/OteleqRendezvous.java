import java.io.IOException;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;

/** Ordinary JDK harness channel shared byte-for-byte by the plain and SDK lanes. */
final class OteleqRendezvous {
  private static String setting(String name, int width) throws IOException {
    String value = System.getenv(name);
    if (value == null || !value.matches("[0-9a-f]{" + width + "}")) {
      throw new IOException("invalid private harness identity");
    }
    return value;
  }

  static void awaitRelease(String action) throws IOException {
    if (Thread.currentThread().isVirtual() || !action.matches("[0-9a-f]{64}")) {
      throw new IOException("unsupported harness action or thread");
    }
    String socket = System.getenv("OTELEQ_ACTION_SOCKET");
    if (socket == null || !Path.of(socket).isAbsolute()) {
      throw new IOException("missing private harness socket");
    }
    String identity = setting("OTELEQ_ACTION_TOKEN", 32) + " "
        + setting("OTELEQ_ACTION_CASE", 64) + " "
        + setting("OTELEQ_ACTION_ATTEMPT", 64) + " " + action + " "
        + ProcessHandle.current().pid() + " " + Thread.currentThread().threadId() + "\n";
    byte[] expected = ("2 release " + identity).getBytes(StandardCharsets.US_ASCII);
    try (SocketChannel channel = SocketChannel.open(StandardProtocolFamily.UNIX)) {
      channel.connect(UnixDomainSocketAddress.of(socket));
      ByteBuffer ready = StandardCharsets.US_ASCII.encode("2 ready " + identity);
      while (ready.hasRemaining()) channel.write(ready);
      ByteBuffer response = ByteBuffer.allocate(expected.length);
      while (response.hasRemaining()) {
        if (channel.read(response) < 0) throw new IOException("incomplete harness release");
      }
      if (!java.util.Arrays.equals(response.array(), expected)) {
        throw new IOException("private harness release identity differs");
      }
    }
  }
}
