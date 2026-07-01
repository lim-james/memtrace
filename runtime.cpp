#include <cstdint>
#include <cstdio>
#include <cstring>
#include <array>
#include <thread>
#include <algorithm>
#include <print> 
#include <map>

#include "spsc/spsc_factory.hpp"

static constexpr std::size_t SHORT_STRING_LENGTH = 64;
using short_string = std::array<char, SHORT_STRING_LENGTH>;

struct MemoryAccess {
    using address_t = std::uintptr_t;

    address_t      address  : 64;
    std::uint32_t  size     : 31;
    bool           is_write : 1;
};

struct MemAccessEvent {
    short_string function_name;
    MemoryAccess memory_access;
};

struct PrettyPrint {
    void process(const MemAccessEvent& event) {
        fprintf(
            stderr, 
            "%s | %u bytes | 0x%016lx | %lu | %s\n", 
            event.memory_access.is_write ? "WRITE" : "READ ", 
            event.memory_access.size, 
            event.memory_access.address & ~63UL,
            event.memory_access.address & 63UL,
            event.function_name.data()
        );
    }
};

struct SimplePrint {
    void process(const MemAccessEvent& event) {
        fprintf(
            stderr, 
            "%s %u %lu\n", 
            event.memory_access.is_write ? "W" : "R", 
            event.memory_access.size, 
            event.memory_access.address
        );
    }
};

class SimpleVisualiser {
    static constexpr std::size_t CACHELINE_SIZE = 64;
    using cacheline_hitmap_t = std::array<std::size_t, CACHELINE_SIZE>;
    using memory_hitmap_t   = std::map<MemoryAccess::address_t, cacheline_hitmap_t>;

public:
    SimpleVisualiser() {
        memory_accesses_.reserve(1'000);
    }

    ~SimpleVisualiser() {
        memory_hitmap_t hitmap{};
        std::size_t max_hit_count = construct_hitmap(hitmap);
        print_hitmap(hitmap, max_hit_count);
    }

    void process(const MemAccessEvent& event) {
        memory_accesses_.push_back(event.memory_access);
    }

private:
    
    std::vector<MemoryAccess> memory_accesses_;

    MemoryAccess::address_t get_cacheline_address(MemoryAccess::address_t address) {
        return address & ~(CACHELINE_SIZE - 1);
    }

    MemoryAccess::address_t get_cacheline_offset(MemoryAccess::address_t address) {
        return address & (CACHELINE_SIZE - 1);
    }

    std::size_t construct_hitmap(memory_hitmap_t& hitmap) {
        std::size_t max_hit_count = 0;

        for (auto& access: memory_accesses_) {
            const auto cacheline_address = get_cacheline_address(access.address);
            const auto cacheline_offset  = get_cacheline_offset(access.address);
            hitmap.try_emplace(cacheline_address, cacheline_hitmap_t{});
            for (auto i{access.size}; i--;) {
                const auto hit_count = ++hitmap.at(cacheline_address).at(cacheline_offset + i);
                max_hit_count = std::max(hit_count, max_hit_count); 
            }
        }

        return max_hit_count;
    }

    void print_hitmap(const memory_hitmap_t& hitmap, std::size_t max_hit_count) {
        for (auto& [cacheline_address, cacheline_hitmap]: hitmap) {
            std::print("{} :: ", cacheline_address);
            for (auto i: cacheline_hitmap) {
                double ratio = static_cast<double>(i) / max_hit_count;
                if (ratio >= 0.9)       std::print("██");
                else if (ratio >= 0.6)  std::print("▓▓");
                else if (ratio >= 0.3)  std::print("▒▒");
                else if (ratio >  0.0)  std::print("░░");
                else std::print("  ");
            }
            std::println();
        }
    }

};

template<typename T>
class MemTraceRuntime {

    static constexpr std::size_t CAPACITY = 1024;
    using ring_buffer_t = SPSCRingBuffer<MemAccessEvent, CAPACITY>;

public:

    MemTraceRuntime() {
        auto [p, c] = make_spsc<MemAccessEvent, CAPACITY>();
        producer = std::move(p); 
        consumer = std::move(c); 

        consumer_worker = std::thread([this] {
            while (true) {
                ConsumeFailure failure;
                auto response = consumer.try_pop(failure); 
                if (!response) {
                    if (failure == ConsumeFailure::BUFFER_CLOSED) {
                        break;
                    } else {
                        continue;
                    }
                }

                response_processor.process(*response);
            }
        });
    }

    ~MemTraceRuntime() noexcept {
        producer.close();
        consumer_worker.join();
    }

    ring_buffer_t::producer_t producer;
    ring_buffer_t::consumer_t consumer;

private:

    std::thread consumer_worker;
    [[no_unique_address]] T response_processor{};

};

static MemTraceRuntime<SimplePrint> runtime;

short_string make_short_string(char* c_str) {
    short_string result{};
    std::copy_n(c_str, std::min(std::strlen(c_str), SHORT_STRING_LENGTH), result.begin());
    return result;
}

extern "C" void __mt_access(
    char*    function_name, 
    void*    addr,
    uint32_t size,
    uint8_t  is_write
) {
    runtime.producer.try_push(MemAccessEvent{
        .function_name = make_short_string(function_name),
        .memory_access = {
            .address       = reinterpret_cast<uintptr_t>(addr),
            .size          = size,
            .is_write      = is_write == 1
        }
    });
}
