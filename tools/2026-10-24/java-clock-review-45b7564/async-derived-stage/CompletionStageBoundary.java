import java.util.concurrent.CompletableFuture;

/** Observe JDK callback side effects without formatting an application throwable. */
public final class CompletionStageBoundary {
  static int formatted;
  static int observed;
  static boolean originalError;

  static final class ApplicationFailure extends RuntimeException {
    private final boolean throwing;
    ApplicationFailure(boolean throwing) { this.throwing = throwing; }
    @Override public String toString() {
      formatted++;
      if (throwing) throw new AssertionError("application formatter executed");
      return "application failure";
    }
  }

  static void check(String mode, boolean throwing) {
    formatted = observed = 0;
    originalError = false;
    var error = new ApplicationFailure(throwing);
    var original = new CompletableFuture<Integer>();
    CompletableFuture<?> dependent = null;
    if (mode.equals("whenComplete")) {
      dependent = original.whenComplete((value, failure) -> {
        observed++;
        originalError = failure == error;
      });
    } else if (mode.equals("handle")) {
      dependent = original.handle((value, failure) -> {
        observed++;
        originalError = failure == error;
        return null;
      });
    }
    String escaped = "none";
    try { original.completeExceptionally(error); }
    catch (Throwable failure) { escaped = failure.getClass().getName(); }
    if (!original.isCompletedExceptionally()) throw new AssertionError("lost original completion");
    if (!mode.equals("baseline") && (observed != 1 || !originalError)) throw new AssertionError("wrong callback");
    if (mode.equals("handle") && (formatted != 0 || !escaped.equals("none") || dependent.isCompletedExceptionally()))
      throw new AssertionError("handle changed completion through formatter");
    if (mode.equals("baseline") && (formatted != 0 || !escaped.equals("none"))) throw new AssertionError("baseline formatted error");
    if (mode.equals("whenComplete") && formatted != 1) throw new AssertionError("missing reproduction");
    System.out.println("{\"mode\":\"" + mode + "\",\"throwing_formatter\":" + throwing
        + ",\"formatter_calls\":" + formatted + ",\"callback_calls\":" + observed
        + ",\"original_error_seen\":" + originalError + ",\"escaped\":\"" + escaped + "\"}");
  }

  public static void main(String[] arguments) {
    for (boolean throwing : new boolean[] {false, true}) {
      for (String mode : new String[] {"baseline", "whenComplete", "handle"}) check(mode, throwing);
    }
  }
}
