#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
__attribute__((noinline)) int workload(int x){return x+7;}
__attribute__((constructor)) static void boot(void){const char*p=getenv("OTELEQ_PROBE_MARKER");if(p){FILE*f=fopen(p,"w");if(f){fputs("constructor\n",f);fclose(f);}}volatile int y=workload(1);(void)y;}
int main(int argc,char**argv){char text[128]={0};if(!fgets(text,sizeof(text),stdin))return 4;
if(argc!=4||strcmp(argv[1],"literal space")||strcmp(argv[2],"--literal")||strcmp(argv[3],"$literal")||strcmp(text,"input $data\n"))return 5;
printf("%ld|%s|%s|%s|%d|%s",(long)getpid(),argv[1],argv[2],argv[3],workload(10),text);return 0;}
