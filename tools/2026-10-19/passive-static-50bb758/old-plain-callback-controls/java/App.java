class App {static class E extends RuntimeException {public String getMessage(){System.out.println("CALLBACK");return "x";}} static int selected(){throw new E();}}
