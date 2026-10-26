__attribute__((noinline)) int workload(int x){return x+7;}
int main(void){return workload(10)==17?0:1;}
