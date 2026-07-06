CXX      := clang++-20
GCC_VER  := 16
GCC_DIR  := /usr/lib/gcc/x86_64-linux-gnu/$(GCC_VER)
GCC_INC  := /usr/include/c++/$(GCC_VER)

SRC_DIR   := src
TEST_DIR  := tests
BUILD_DIR := build

CXXFLAGS := -std=c++23 \
             --gcc-toolchain=$(GCC_DIR) \
             -B$(GCC_DIR) \
             -I$(GCC_INC) \
             -I/usr/include/x86_64-linux-gnu/c++/$(GCC_VER) \
             -I$(GCC_INC)/backward \
			 -L$(GCC_DIR)
PASSFLAGS := $(CXXFLAGS) \
             -shared -fPIC -fno-rtti \
             $(filter-out -fno-exceptions, $(shell llvm-config-20 --cxxflags)) \
             -L$(GCC_DIR) \
             $(shell llvm-config-20 --ldflags)

PASS_SO   := $(BUILD_DIR)/mem_trace_pass.so
RUNTIME_O := $(BUILD_DIR)/runtime.o

.PHONY: all clean
all: $(PASS_SO) $(RUNTIME_O)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(PASS_SO): $(SRC_DIR)/mem_trace_pass.cpp | $(BUILD_DIR)
	$(CXX) $(PASSFLAGS) $< -o $@

$(RUNTIME_O): $(SRC_DIR)/runtime.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -c $< -o $@

# compile a target program with the pass and link runtime
# usage: make test TARGET=test_array.cpp
test: $(PASS_SO) $(RUNTIME_O)
	$(CXX) $(CXXFLAGS) -fpass-plugin=./$(PASS_SO) -g $(RUNTIME_O) $(TEST_DIR)/$(TARGET) -o $(BUILD_DIR)/test

clean:
	rm -f $(PASS_SO) $(RUNTIME_O) $(BUILD_DIR)/test
