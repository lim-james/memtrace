#pragma once

#include "ring_buffer.hpp"
#include "producer.hpp"
#include "consumer.hpp"

#include <vector>

template<typename buffer_t>
struct SPSCPack {
    using producer_t = buffer_t::producer_t;
    using consumer_t = buffer_t::consumer_t;

    producer_t producer;
    consumer_t consumer;
};

template<std::copyable T, std::size_t Capacity>
[[nodiscard]] auto make_spsc() {
    using buffer_t   = SPSCRingBuffer<T, Capacity>;
    using producer_t = buffer_t::producer_t;
    using consumer_t = buffer_t::consumer_t;

    auto shared_buffer = std::make_shared<buffer_t>();

    return SPSCPack<buffer_t>{
        .producer = producer_t{shared_buffer}, 
        .consumer = consumer_t{shared_buffer}
    };
}
