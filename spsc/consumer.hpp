#pragma once

#include "types.hpp"

#include <optional>
#include <memory>

template<typename buffer_t>
class SPSCConsumer {
    
    using T = buffer_t::value_t;
    using shared_buffer_t = std::shared_ptr<buffer_t>;

    static constexpr auto CAPACITY = buffer_t::capacity();
    static constexpr auto MASK     = CAPACITY - 1;

public:

    SPSCConsumer() = default;

    explicit SPSCConsumer(shared_buffer_t buffer)
        : buffer_(buffer) 
        , control_block_(buffer->register_consumer()) {}

    ~SPSCConsumer() noexcept = default;

    SPSCConsumer(const SPSCConsumer&)   = delete;
    void operator=(const SPSCConsumer&) = delete;

    SPSCConsumer(SPSCConsumer&&) noexcept = default;
    SPSCConsumer& operator=(SPSCConsumer&&) noexcept = default;

    std::optional<T> try_pop(ConsumeFailure& failure) {
        auto read_idx = control_block_->read_idx_.load(std::memory_order_relaxed);
        
        if (failure = check_pop_status(read_idx); failure != ConsumeFailure::NONE) {
            return std::nullopt;
        }

        T item = buffer_->buffer_[read_idx & MASK];
        control_block_->read_idx_.store(read_idx + 1, std::memory_order_release);
        return item;
    }

    ConsumeFailure try_pop_many(std::size_t count, std::span<T> read_ptr) {
        assert(read_ptr.size() >= count);

        auto read_idx = control_block_->read_idx_.load(std::memory_order_relaxed);
        
        if (auto failure = check_pop_status(read_idx, count); failure != ConsumeFailure::NONE) {
            return failure;
        }

        for (std::size_t i = 0; i < count; ++i)
            read_ptr[i] = buffer_->buffer_[(read_idx + i) & MASK];

        control_block_->read_idx_.store(read_idx + count, std::memory_order_release);
        return ConsumeFailure::NONE;
    }

    ConsumeFailure try_skip_many(std::size_t count) {
        auto read_idx = control_block_->read_idx_.load(std::memory_order_relaxed);
        
        if (auto failure = check_pop_status(read_idx, count); failure != ConsumeFailure::NONE) {
            return failure;
        }

        control_block_->read_idx_.store(read_idx + count, std::memory_order_release);
        return ConsumeFailure::NONE;
    }

private:

    std::size_t cached_write_idx_{};

    shared_buffer_t buffer_;
    SPSCConsumerControlBlock* control_block_;

    ConsumeFailure check_pop_status(std::size_t read_idx, std::size_t count = 1) {
        if (cached_write_idx_ - read_idx < count) {
            cached_write_idx_ = buffer_->write_idx_.load(std::memory_order_acquire);
            if (cached_write_idx_ - read_idx < count) {
                return buffer_->is_closed_.load(std::memory_order_acquire)
                    ? ConsumeFailure::BUFFER_CLOSED
                    : ConsumeFailure::BUFFER_INSUFFICIENT;
            }
        }
        return ConsumeFailure::NONE;
    }

};
