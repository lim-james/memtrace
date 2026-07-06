#pragma once

#include "types.hpp"

#include <new>
#include <atomic>
#include <expected>
#include <concepts>
#include <span>
#include <memory>
#include <cassert>
#include <limits>

template<std::copyable T, std::size_t Capacity>
class SPSCRingBuffer {

    using value_t = T;

    static_assert(Capacity > 0 && "Capacity cannot be empty");
    static_assert((Capacity & (Capacity - 1)) == 0 && "Capacity must be power of 2");

public:

    using producer_t = SPSCProducer<SPSCRingBuffer>;
    using consumer_t = SPSCConsumer<SPSCRingBuffer>;

    SPSCRingBuffer()  = default;
    ~SPSCRingBuffer() = default;

    SPSCRingBuffer(const SPSCRingBuffer&) = delete;
    void operator=(const SPSCRingBuffer&) = delete;

    SPSCRingBuffer(SPSCRingBuffer&&) = delete;
    void operator=(SPSCRingBuffer&&) = delete;

    static constexpr std::size_t capacity() noexcept {
        return Capacity;
    }

    [[nodiscard]] auto register_consumer() -> SPSCConsumerControlBlock* {
        return &consumer_;
    }

private:

    std::atomic<bool> is_closed_ = false;
    std::unique_ptr<T[]> buffer_ = std::make_unique<T[]>(Capacity);
    
    alignas(64)
    std::atomic<std::size_t> write_idx_ = 0;

    SPSCConsumerControlBlock consumer_{};

    friend class SPSCProducer<SPSCRingBuffer>;
    friend class SPSCConsumer<SPSCRingBuffer>;

};
