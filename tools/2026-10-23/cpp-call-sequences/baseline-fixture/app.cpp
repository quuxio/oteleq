class Counter {int value_;inline static int total_=0;public:explicit Counter(int start):value_(start){} int step(int amount){value_+=amount;total_+=amount;return value_;}};
