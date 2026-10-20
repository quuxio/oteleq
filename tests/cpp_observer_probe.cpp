// Exercise the actual fixed-arena observer, including refusal paths.
#include "cpp_observe.hpp"
#include <string>

using __oteleq_cpp::Graph;
using __oteleq_cpp::capture_failure;

template<class F> void refuses(F operation) {
    try { operation(); } catch (const capture_failure&) { return; }
    std::abort();
}

static void integer(Graph& graph, const void* address, unsigned depth) {
    graph.field("\"location\""); graph.location(address, depth + 1);
    graph.field("\"value\""); graph.scalar("\"int\"", address, sizeof(int));
}

template<class T> void exception() {
    Graph graph; graph.begin(); graph.field("\"error\""); graph.error(T("message")); graph.finish();
}

class UnknownException : public std::exception {
    const char* what() const noexcept override { std::abort(); }
};

int main() {
    int value = 7;
    Graph graph; graph.begin();
    graph.field("\"first\""); graph.reference(0, "\"cpp.storage:int\"", &value, integer, 0);
    graph.field("\"alias\""); graph.reference(0, "\"cpp.storage:int\"", &value, integer, 0);
    graph.field("\"null\""); graph.absent();
    graph.field("\"unit\""); graph.unit();
    graph.item(0); graph.scalar("\"int\"", &value, sizeof(value));
    graph.finish();
    std::FILE* output = std::tmpfile(); if (!output) return 1;
    if (!graph.write(output) || std::fclose(output)) return 2;
    output = std::fopen(__FILE__, "rb"); if (!output) return 3;
    if (graph.write(output) || std::fclose(output)) return 4;

    refuses([&]{Graph g; g.reference(0, "\"x\"", nullptr, nullptr, 0);});
    refuses([&]{Graph g; g.reference(0, "\"x\"", &value, nullptr, 33);});
    refuses([]{Graph g; int values[513]{}; for (int& item:values) g.location(&item, 0);});
    refuses([]{Graph g; for (int i=0;i<8193;++i) g.field("\"x\"");});
    refuses([]{Graph g; char chunk[1025]; std::memset(chunk,'a',1024);chunk[1024]=0;
        for(int i=0;i<256;++i)g.text(chunk);g.text("x");});
    refuses([&]{Graph g; g.raw(&value,131073);});
    refuses([]{Graph g; g.error(UnknownException{});});
    refuses([]{Graph g; g.error(std::runtime_error(std::string(65537,'a')));});
    {Graph g; g.error(std::exception{});}
    exception<std::runtime_error>(); exception<std::logic_error>();
    exception<std::invalid_argument>(); exception<std::domain_error>();
    exception<std::length_error>(); exception<std::out_of_range>();
    exception<std::range_error>(); exception<std::overflow_error>(); exception<std::underflow_error>();
    return 0;
}
