#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <unistd.h>
__attribute__((noinline)) int workload(int x){if(x<0)throw std::runtime_error("original");return x+7;}
struct Item{Item(){const char*p=std::getenv("CTOR_MARKER");if(p){FILE*f=std::fopen(p,"w");if(f){std::fputs("ctor\n",f);std::fclose(f);}}workload(1);}};Item item;
int main(int argc,char**argv){std::printf("ready %ld %s\n",(long)getpid(),argc>1?argv[1]:"none");std::fflush(stdout);int x;while(std::scanf("%d",&x)==1){if(x==99)return 23;try{std::printf("%d\n",workload(x));}catch(const std::exception&e){std::printf("%s\n",e.what());}std::fflush(stdout);}return 0;}
