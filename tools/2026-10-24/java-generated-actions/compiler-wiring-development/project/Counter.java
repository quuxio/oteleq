class Counter {
private int value;private Counter(int initial){value=initial;}
private static Counter make(int initial){return new Counter(initial);}
private Counter run(int amount){value+=amount;return this;}
}