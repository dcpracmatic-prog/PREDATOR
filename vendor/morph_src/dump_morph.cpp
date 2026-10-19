// dump_morph — vertex-list front-end for MORPH (Zero-Trust Graph Engine)
// Usage: dump_morph <graph.gph> <budget_ms> <seed>
// Output: "# <size>" then one 1-indexed vertex per line.
#define main morph_qoblib_cli_main
#include "morph_qoblib_solver.cpp"
#undef main

#include <iostream>
#include <string>

int main(int argc, char** argv) {
    if (argc < 4) {
        std::cerr << "usage: dump_morph <graph.gph> <budget_ms> <seed>\n";
        return 2;
    }
    try {
        Graph g = load_graph(argv[1]);
        int budget_ms = std::stoi(argv[2]);
        uint64_t seed = std::stoull(argv[3]);
        Solution s = morph(g, seed, budget_ms);
        std::cout << "# " << s.size << "\n";
        for (int v = 0; v < g.n; ++v) {
            if (s.x[v]) std::cout << (v + 1) << "\n";
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "dump_morph error: " << e.what() << "\n";
        return 1;
    }
}
