
import java.io.*;
public final class Harness {
  static final BufferedReader INPUT = new BufferedReader(new InputStreamReader(System.in));
  static void rendezvous() throws IOException {
    System.out.println("release");
    if (!"go".equals(INPUT.readLine())) throw new IOException("missing release");
  }
  static int wrapper(int seed) { return Work.target(seed); }
  static int envelope(int seed) throws IOException { rendezvous(); return wrapper(seed); }
  public static void main(String[] args) throws IOException {
    System.out.println("ready");
    for (String line; (line = INPUT.readLine()) != null && !line.equals("quit");) {
      try {
        int value = envelope(Integer.parseInt(line));
        System.out.println("{\"value\":" + value + ",\"getters\":" + Work.getters + "}");
      } catch (Work.Problem error) {
        System.out.println("{\"error\":true,\"same\":" + (error == Work.FAILURE) + ",\"getters\":" + Work.getters + "}");
      }
    }
  }
}
final class Work {
  static int getters;
  static final Problem FAILURE = new Problem();
  static int target(int seed) { if (seed < 0) throw FAILURE; return seed + 1; }
  static final class Problem extends RuntimeException {
    @Override public String getMessage() { getters++; return "changed"; }
    @Override public String toString() { getters++; return "changed"; }
    @Override public synchronized Throwable getCause() { getters++; return this; }
  }
}
