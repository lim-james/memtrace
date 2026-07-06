#include <cstdio>
#include <vector>

static constexpr std::size_t SAMPLE_SIZE = 100'000;

int main() {
    auto lcg = [state = 42u]() mutable -> unsigned {
        state = state * 1664525u + 1013904223u;
        return state >> 1;
    };

    auto val = [&]{ return static_cast<int>(lcg() % 1'000'000); };

    std::vector<int> vector;
    vector.reserve(SAMPLE_SIZE);

    int hits = 0;
    for (auto i{SAMPLE_SIZE}; i--;) {
        vector.push_back(val());
        ++hits;
    }

    std::printf("Read hits: %d / %zu\n", hits, SAMPLE_SIZE / 2);
}
