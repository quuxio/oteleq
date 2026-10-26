#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
__attribute__((noinline)) int workload(int x){return x+7;}
struct Boot{Boot(){const char*p=std::getenv("OTELEQ_PROBE_MARKER");if(p){FILE*f=std::fopen(p,"w");if(f){std::fputs("constructor\n",f);std::fclose(f);}}volatile int y=workload(1);(void)y;}};Boot boot;
int main(int argc,char**argv){char text[128]={};if(!std::fgets(text,sizeof(text),stdin))return 4;
if(argc!=4||std::strcmp(argv[1],"literal space")||std::strcmp(argv[2],"--literal")||std::strcmp(argv[3],"$literal")||std::strcmp(text,"input $data\n"))return 5;
std::printf("%ld|%s|%s|%s|%d|%s",(long)getpid(),argv[1],argv[2],argv[3],workload(10),text);return 0;}
