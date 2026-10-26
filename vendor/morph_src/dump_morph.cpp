// dump_morph — vertex-list front-end for MORPH (Zero-Trust Graph Engine)
// Usage: dump_morph <graph.gph> <budget_ms> <seed>
// Output: "# <size>" then one 1-indexed vertex per line.
#define main morph_qoblib_cli_main
#include "morph_qoblib_solver.cpp"
#undef main

#include <iostream>
#include <limits>
#include <string>
#include <chrono>
#include <sstream>
#include <cstdio>
#include <memory>
#include "json_graph_stream.hpp"

int main(int argc, char** argv) {
    const bool json_mode = argc == 3 && std::string(argv[1]) == "--json";
    if ((!json_mode && argc != 4) || (json_mode && argc != 3)) {
        std::cerr << "usage: dump_morph [--json <request.json>] | <graph.gph> <budget_ms> <seed>\n";
        return 2;
    }
    const char* input_path = argv[json_mode ? 2 : 1];
    try {
        Graph g;
        std::shared_ptr<FILE> parsed_spool;
        size_t parsed_m = 0;
        int budget_ms = 100;
        uint64_t seed = 1;
        double json_parse_ms = 0.0;
        double graph_build_ms = 0.0;
        if (json_mode) {
            const auto parse_started = std::chrono::steady_clock::now();
            JsonGraph parsed = load_json_graph(input_path);
            const auto parsed_at = std::chrono::steady_clock::now();
            json_parse_ms = std::chrono::duration<double, std::milli>(parsed_at - parse_started).count();
            budget_ms = parsed.budget_ms;
            seed = parsed.seed;
            parsed_spool = parsed.edge_spool;
            parsed_m = parsed.m;
            const auto build_started = std::chrono::steady_clock::now();
            g.n = parsed.n;
            g.deg = std::move(parsed.degree);
            g.off.assign(static_cast<size_t>(g.n) + 1, 0);
            for (int i = 0; i < g.n; ++i) g.off[i + 1] = g.off[i] + g.deg[i];
            g.adj.resize(static_cast<size_t>(g.off[g.n]));
            std::vector<int> cursor = g.off;
            uint32_t pair[2];
            for (size_t i = 0; i < parsed.m; ++i) {
                if (std::fread(pair, sizeof(pair), 1, parsed.edge_spool.get()) != 1)
                    throw std::runtime_error("truncated native edge spool");
                const int u = static_cast<int>(pair[0]), v = static_cast<int>(pair[1]);
                g.adj[cursor[u]++] = v;
                g.adj[cursor[v]++] = u;
            }
            for (int v = 0; v < g.n; ++v) {
                std::sort(g.adj.begin() + g.off[v], g.adj.begin() + g.off[v + 1]);
                if (std::adjacent_find(g.adj.begin() + g.off[v], g.adj.begin() + g.off[v + 1]) != g.adj.begin() + g.off[v + 1])
                    throw std::runtime_error("duplicate edge in graph.edges");
            }
            graph_build_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - build_started).count();
        } else {
            g = load_graph(input_path);
        }

        if (!json_mode) {
            const std::string budget_text(argv[2]);
            std::size_t budget_pos = 0;
            const long long parsed_budget = std::stoll(budget_text, &budget_pos, 10);
            if (budget_pos != budget_text.size() || parsed_budget <= 0 ||
                parsed_budget > std::numeric_limits<int>::max()) {
                throw std::invalid_argument("budget_ms must be a positive 32-bit integer");
            }
            budget_ms = static_cast<int>(parsed_budget);
            const std::string seed_text(argv[3]);
            if (seed_text.empty() || seed_text.front() == '-')
                throw std::invalid_argument("seed must be an unsigned 64-bit integer");
            std::size_t seed_pos = 0;
            const unsigned long long parsed_seed = std::stoull(seed_text, &seed_pos, 10);
            if (seed_pos != seed_text.size())
                throw std::invalid_argument("seed must be an unsigned 64-bit integer");
            seed = static_cast<uint64_t>(parsed_seed);
        }
        const auto started = std::chrono::steady_clock::now();
        Solution s = morph(g, seed, budget_ms);
        const auto solved = std::chrono::steady_clock::now();
        bool verified = valid(g, s);
        if (json_mode && verified) {
            // Check the original edge stream, independently of the CSR verifier.
            if (std::fseek(parsed_spool.get(), 0, SEEK_SET) != 0) verified = false;
            uint32_t pair[2];
            for (size_t i = 0; verified && i < parsed_m; ++i) {
                if (std::fread(pair, sizeof(pair), 1, parsed_spool.get()) != 1 ||
                    (s.x[pair[0]] && s.x[pair[1]])) verified = false;
            }
        }
        const auto verified_at = std::chrono::steady_clock::now();
        if (!verified) throw std::runtime_error("native solver produced an invalid independent set");
        const double solver_ms = std::chrono::duration<double, std::milli>(solved - started).count();
        const double verification_ms = std::chrono::duration<double, std::milli>(verified_at - solved).count();
        if (json_mode) {
            const auto serialize_started = std::chrono::steady_clock::now();
            std::ostringstream output;
            output << "{\"n\":" << g.n << ",\"m\":" << g.adj.size() / 2
                   << ",\"size\":" << s.size << ",\"verified\":true,\"budget_ms\":" << budget_ms
                   << ",\"seed\":" << seed << ",\"json_parse_ms\":" << json_parse_ms
                   << ",\"graph_build_ms\":" << graph_build_ms << ",\"solver_ms\":" << solver_ms
                   << ",\"verification_ms\":" << verification_ms << ",\"nodes\":[";
            bool first = true;
            for (int v = 0; v < g.n; ++v) if (s.x[v]) {
                if (!first) output << ',';
                output << v;
                first = false;
            }
            const double serialization_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - serialize_started).count();
            const double total_ms = json_parse_ms + graph_build_ms + solver_ms + verification_ms + serialization_ms;
            output << "],\"serialization_ms\":" << serialization_ms << ",\"total_ms\":" << total_ms << "}\n";
            const auto write_started = std::chrono::steady_clock::now();
            std::cout << output.str() << std::flush;
            const double output_write_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - write_started).count();
            (void)output_write_ms;
        } else {
            std::cout << "# " << s.size << "\n";
            for (int v = 0; v < g.n; ++v) if (s.x[v]) std::cout << (v + 1) << "\n";
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "dump_morph error: " << e.what() << "\n";
        return 1;
    }
}
