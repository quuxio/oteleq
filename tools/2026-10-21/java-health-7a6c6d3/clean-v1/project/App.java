final class App {
 private int value;
 private static int total=0;
 App(int seed){value=seed;}
 int add(int amount){value+=amount;total+=amount;return value;}
}
