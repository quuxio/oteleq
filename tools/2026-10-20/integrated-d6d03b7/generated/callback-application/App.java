class App {
static class E extends RuntimeException {
 public String getMessage(){System.out.println("CALLBACK");return "masked";}
}
static int selected(){throw new E();}
}
