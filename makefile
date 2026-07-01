CXX      := clang++-20
GCC_VER  := 16
GCC_DIR  := /usr/lib/gcc/x86_64-linux-gnu/$(GCC_VER)
GCC_INC  := /usr/include/c++/$(GCC_VER)

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

.PHONY: all clean

all: mem_trace_pass.so runtime.o

mem_trace_pass.so: mem_trace_pass.cpp
	$(CXX) $(PASSFLAGS) $< -o $@

runtime.o: runtime.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

# compile a target program with the pass and link runtime
# usage: make TARGET=test.cpp
test: mem_trace_pass.so runtime.o
	$(CXX) $(CXXFLAGS) -fpass-plugin=./mem_trace_pass.so runtime.o $(TARGET) -o test

clean:
	rm -f mem_trace_pass.so runtime.o test
