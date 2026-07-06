#include <flat_map>
#include <cstdio> 

static constexpr std::size_t SAMPLE_SIZE = 100'000;
static constexpr std::size_t KEY_SAMPLE_SIZE = 100;

int main() {
    std::flat_map<int, int> map;

    auto lcg = [state = 42u]() mutable -> unsigned {
        state = state * 1664525u + 1013904223u;
        return state >> 1;
    };

    auto key = [&]{ return static_cast<int>(lcg() % KEY_SAMPLE_SIZE); };
    auto val = [&]{ return static_cast<int>(lcg() % 1'000'000); };

    for (auto i{SAMPLE_SIZE}; i--;) {
        map[key()] = val();
    }

    int hits = 0;
    for (auto i{SAMPLE_SIZE}; i--;) {
        if (lcg() & 1) {
            map[key()] = val();
        } else {
            auto it = map.find(key());
            if (it != map.end()) ++hits;
        }
    }

    std::printf("Map size:  %zu\n", map.size());
    std::printf("Read hits: %d / %zu\n", hits, SAMPLE_SIZE / 2);
}
