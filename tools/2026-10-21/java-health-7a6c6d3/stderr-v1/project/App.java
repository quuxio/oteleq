final class App {
 private int value;
 private static int total=0;
 App(int seed){value=seed;}
 int add(int amount){java.lang.System.err.println("[otel.javaagent 2026-10-21 00:00:00:000 +0000] [main] INFO io.opentelemetry.javaagent.tooling.VersionLogger - opentelemetry-javaagent - version: 2.32.0");java.lang.System.err.println("OpenJDK 64-Bit Server VM warning: Sharing is only supported for boot loader classes because bootstrap classpath has been appended");value+=amount;total+=amount;return value;}
}
