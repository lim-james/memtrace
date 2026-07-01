#pragma once

#include <atomic>
#include <cstdint>
#include <type_traits>

template<typename buffer_t> class SPSCProducer;
template<typename buffer_t> class SPSCConsumer;

struct SPSCConsumerControlBlock {
    alignas(64) std::atomic<std::size_t> read_idx_ = 0;
};

template<std::copyable T, std::size_t Capacity>
class SPSCRingBuffer;

enum class ProduceResponse: std::uint8_t { 
    SUCCESS, 
    FAILED_BUFFER_FULL, FAILED_PAYLOAD_TOO_LARGE 
};

enum class ConsumeFailure: std::uint8_t { NONE, BUFFER_INSUFFICIENT, BUFFER_CLOSED };
