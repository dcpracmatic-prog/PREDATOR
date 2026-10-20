// dump_morph — vertex-list front-end for MORPH (Zero-Trust Graph Engine)
// Usage: dump_morph <graph.gph> <budget_ms> <seed>
// Output: "# <size>" then one 1-indexed vertex per line.
#define main morph_qoblib_cli_main
#include "morph_qoblib_solver.cpp"
#undef main

#include <iostream>
#include <limits>
#include <string>

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: dump_morph <graph.gph> <budget_ms> <seed>\\n";
        return 2;
    }
    try {
        Graph g = load_graph(argv[1]);

        const std::string budget_text(argv[2]);
        std::size_t budget_pos = 0;
        const long long parsed_budget = std::stoll(budget_text, &budget_pos, 10);
        if (budget_pos != budget_text.size() || parsed_budget <= 0 ||
            parsed_budget > std::numeric_limits<int>::max()) {
            throw std::invalid_argument("budget_ms must be a positive 32-bit integer");
        }
        const int budget_ms = static_cast<int>(parsed_budget);

        const std::string seed_text(argv[3]);
        if (seed_text.empty() || seed_text.front() == '-') {
            throw std::invalid_argument("seed must be an unsigned 64-bit integer");
        }
        std::size_t seed_pos = 0;
        const unsigned long long parsed_seed = std::stoull(seed_text, &seed_pos, 10);
        if (seed_pos != seed_text.size()) {
            throw std::invalid_argument("seed must be an unsigned 64-bit integer");
        }
        const uint64_t seed = static_cast<uint64_t>(parsed_seed);

        Solution s = morph(g, seed, budget_ms);
        std::cout << "# " << s.size << "\\n";
        for (int v = 0; v < g.n; ++v) {
            if (s.x[v]) std::cout << (v + 1) << "\\n";
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "dump_morph error: " << e.what() << "\\n";
        return 1;
    }
}
