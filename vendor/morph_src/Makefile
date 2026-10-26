CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -DNDEBUG

.PHONY: all clean

all: morph_v15 morph_qoblib_solver dump_morph

morph_v15: morph_v15.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

morph_qoblib_solver: morph_qoblib_solver.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

dump_morph: dump_morph.cpp morph_qoblib_solver.cpp json_graph_stream.hpp
	$(CXX) $(CXXFLAGS) -o $@ dump_morph.cpp

clean:
	rm -f morph_v15 morph_qoblib_solver dump_morph
