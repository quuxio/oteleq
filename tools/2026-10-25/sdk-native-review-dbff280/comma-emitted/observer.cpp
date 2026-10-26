#include "resource_abi.h"
#include "function_abi.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <set>
struct Counts {std::uint64_t admitted=0,completed=0,live=0,untracked=0;};
Counts counts;
std::map<const void*,std::uint64_t> active;
std::set<std::uint64_t> pending;
extern "C" void otelc_function_register_v1(const otelc_function_descriptor_v1*,std::uint64_t n) noexcept {assert(n==0);}
extern "C" std::uint64_t otelc_function_enter_v1(const void*) noexcept{return 0;}
extern "C" void otelc_function_leave_v1(std::uint64_t,std::int32_t) noexcept{}
extern "C" void otelc_resource_allocated_v1(const void*p,const char*usr,const char*name) noexcept {
 assert(p&&usr&&name);auto token=++counts.admitted;
 assert(active.emplace(p,token).second);++counts.live;
}
extern "C" std::uint64_t otelc_resource_releasing_v1(const void*p) noexcept {
 auto found=active.find(p);if(found==active.end()){++counts.untracked;return 0;}
 auto token=found->second;active.erase(found);pending.insert(token);--counts.live;return token;
}
extern "C" void otelc_resource_released_v1(std::uint64_t token) noexcept {
 if(token){assert(pending.erase(token)==1);++counts.completed;}
}
__attribute__((destructor)) static void report(){
 const char*path=std::getenv("RESOURCE_TEST_OUTPUT");assert(path);
 auto*f=std::fopen(path,"wx");assert(f);
 std::fprintf(f,"{\"admitted\":%llu,\"completed\":%llu,\"live\":%llu,\"untracked\":%llu}\n",
  (unsigned long long)counts.admitted,(unsigned long long)counts.completed,
  (unsigned long long)counts.live,(unsigned long long)counts.untracked);std::fclose(f);
}
