// Bounded passive native storage capture. Application formatters are never used.
#ifndef OTELEQ_CPP_OBSERVE_HPP
#define OTELEQ_CPP_OBSERVE_HPP
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <stdexcept>
#include <type_traits>
#include <typeinfo>

namespace __oteleq_cpp {
template<class> struct access;
struct capture_failure { const char* reason; };

// A fixed arena avoids application operator new/delete during observation.
class Graph {
public:
    using Writer = void (*)(Graph&, const void*, unsigned);
private:
    struct Node { const void* address; int type; const char* label; Writer writer; unsigned depth; };
    Node nodes_[512];
    char bytes_[262144];
    std::size_t used_ = 0, count_ = 0, fields_ = 0;
    bool comma_ = false;

    std::size_t node(int type, const char* label, const void* address, Writer writer, unsigned depth) {
        for (std::size_t i = 0; i < count_; ++i)
            if (nodes_[i].address == address && nodes_[i].type == type) return i;
        if (!address || count_ == 512 || depth > 32) throw capture_failure{"storage/depth budget or invalid address"};
        std::size_t index = count_++;
        nodes_[index] = {address, type, label, writer, depth};
        return index;
    }
public:
    void text(const char* value) {
        std::size_t size = std::strlen(value);
        if (size > sizeof(bytes_) - used_) throw capture_failure{"graph byte budget"};
        std::memcpy(bytes_ + used_, value, size); used_ += size;
    }
    void number(std::size_t value) {
        char digits[32]; std::snprintf(digits, sizeof(digits), "%zu", value); text(digits);
    }
    void raw(const void* value, std::size_t size) {
        static constexpr char digits[] = "0123456789abcdef";
        if (size > (sizeof(bytes_) - used_) / 2) throw capture_failure{"raw byte budget"};
        auto bytes = static_cast<const unsigned char*>(value);
        for (std::size_t i = 0; i < size; ++i) {
            bytes_[used_++] = digits[bytes[i] >> 4]; bytes_[used_++] = digits[bytes[i] & 15];
        }
    }
    void field(const char* quoted_name) {
        if (++fields_ > 8192) throw capture_failure{"field budget"};
        if (comma_) text(","); comma_ = true; text(quoted_name); text(":");
    }
    void item(std::size_t index) {
        char name[32]; std::snprintf(name, sizeof(name), "\"item:%zu\"", index); field(name);
    }
    void reference(int type, const char* label, const void* address, Writer writer, unsigned depth) {
        auto index = node(type, label, address, writer, depth);
        text("{\"kind\":\"reference\",\"node_id\":\"n"); number(index); text("\"}");
    }
    void location(const void* address, unsigned depth) {
        reference(-1, "\"cpp.location\"", address, nullptr, depth);
    }
    void absent() { text("{\"kind\":\"null\"}"); }
    void unit() { text("{\"kind\":\"unit\",\"type\":\"cpp.unit\"}"); }
    void scalar(const char* quoted_type, const void* value, std::size_t size) {
        text("{\"native_type\":"); text(quoted_type); text(",\"bytes\":\""); raw(value, size); text("\"}");
    }
    void error(const std::exception& error) {
        const auto& type = typeid(error);
        const char* label = nullptr;
#define OTELEQ_CPP_EXCEPTION(T) if (type == typeid(T)) label = "\"" #T "\"";
        OTELEQ_CPP_EXCEPTION(std::exception)
        OTELEQ_CPP_EXCEPTION(std::runtime_error) OTELEQ_CPP_EXCEPTION(std::logic_error)
        OTELEQ_CPP_EXCEPTION(std::invalid_argument) OTELEQ_CPP_EXCEPTION(std::domain_error)
        OTELEQ_CPP_EXCEPTION(std::length_error) OTELEQ_CPP_EXCEPTION(std::out_of_range)
        OTELEQ_CPP_EXCEPTION(std::range_error) OTELEQ_CPP_EXCEPTION(std::overflow_error)
        OTELEQ_CPP_EXCEPTION(std::underflow_error)
#undef OTELEQ_CPP_EXCEPTION
        if (!label) throw capture_failure{"exception accessor needs a qualified codec"};
        const char* message = error.what();
        if (!message) throw capture_failure{"absent exception message"};
        std::size_t size = 0;
        while (size <= 65536 && message[size]) ++size;
        if (size > 65536) throw capture_failure{"exception message budget"};
        text("{\"error_type\":"); text(label); text(",\"message\":\""); raw(message, size); text("\"}");
    }
    void begin() { text("{\"roots\":{"); comma_ = false; }
    void finish() {
        text("},\"nodes\":[");
        // Writers may append views. Indices survive additions and cycles never recurse.
        for (std::size_t i = 0; i < count_; ++i) {
            Node value = nodes_[i];
            if (i) text(",");
            text("{\"id\":\"n"); number(i); text("\",\"type\":"); text(value.label); text(",\"fields\":{");
            comma_ = false;
            if (value.writer) value.writer(*this, value.address, value.depth);
            text("}}");
        }
        text("]}");
    }
    bool write(std::FILE* output) const { return std::fwrite(bytes_, 1, used_, output) == used_; }
};
}
#endif
