#pragma once

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <cstdio>
#include <memory>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <unordered_set>
#include <unistd.h>
#include <vector>

// Small bounded-memory JSON reader for the graph request shape used by PREDATOR.
// Edge pairs are stored as native integers, never as Python objects.
struct JsonGraph {
    int n = -1;
    int budget_ms = 100;
    uint64_t seed = 1;
    std::string method = "morph";
    bool directed = false;
    size_t m = 0;
    std::vector<int> degree;
    std::shared_ptr<FILE> edge_spool;
};

class JsonScanner {
public:
    explicit JsonScanner(const std::string& path) : input_(path, std::ios::binary) {
        if (!input_) throw std::runtime_error("cannot open JSON graph file");
    }

    struct Token { char kind; std::string value; bool truncated = false; };

    Token next() {
        skip_ws();
        int c = peek();
        if (c == EOF) return {'e', {}};
        if (c == '{' || c == '}' || c == '[' || c == ']' || c == ':' || c == ',') {
            take(); return {static_cast<char>(c), {}};
        }
        if (c == '"') { bool truncated = false; auto value = read_string(truncated); return {'s', std::move(value), truncated}; }
        if (c == '-' || (c >= '0' && c <= '9')) return {'n', read_number()};
        if (c == 't') { read_literal("true"); return {'b', "true"}; }
        if (c == 'f') { read_literal("false"); return {'b', "false"}; }
        if (c == 'n') { read_literal("null"); return {'z', "null"}; }
        throw std::runtime_error("invalid JSON token");
    }

    void skip_value(Token token, int depth = 0) {
        if (depth > 64) throw std::runtime_error("JSON nesting exceeds 64 levels");
        if (token.kind == '{') {
            Token t = next();
            if (t.kind == '}') return;
            std::unordered_set<std::string> keys;
            while (true) {
                if (keys.size() >= 64) throw std::runtime_error("JSON object exceeds 64-member parser limit");
                if (t.kind != 's' || t.truncated || next().kind != ':') throw std::runtime_error("malformed JSON object key");
                if (!keys.insert(t.value).second) throw std::runtime_error("duplicate JSON object key");
                skip_value(next(), depth + 1);
                t = next();
                if (t.kind == '}') return;
                if (t.kind != ',') throw std::runtime_error("malformed JSON object separator");
                t = next();
            }
        }
        if (token.kind == '[') {
            Token t = next();
            if (t.kind == ']') return;
            while (true) {
                skip_value(t, depth + 1);
                t = next();
                if (t.kind == ']') return;
                if (t.kind != ',') throw std::runtime_error("malformed JSON array separator");
                t = next();
            }
        }
        if (token.kind != 's' && token.kind != 'n' && token.kind != 'b' && token.kind != 'z')
            throw std::runtime_error("expected JSON value");
    }

private:
    std::ifstream input_;
    int peek() { return input_.peek(); }
    int take() { return input_.get(); }
    void skip_ws() { while (true) { int c = peek(); if (c == ' ' || c == '\t' || c == '\r' || c == '\n') take(); else break; } }
    static int hex(int c) {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    }
    static void append_utf8(std::string& out, uint32_t cp) {
        if (cp <= 0x7f) out.push_back(static_cast<char>(cp));
        else if (cp <= 0x7ff) { out.push_back(static_cast<char>(0xc0 | (cp >> 6))); out.push_back(static_cast<char>(0x80 | (cp & 0x3f))); }
        else if (cp <= 0xffff) { out.push_back(static_cast<char>(0xe0 | (cp >> 12))); out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f))); out.push_back(static_cast<char>(0x80 | (cp & 0x3f))); }
        else { out.push_back(static_cast<char>(0xf0 | (cp >> 18))); out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3f))); out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f))); out.push_back(static_cast<char>(0x80 | (cp & 0x3f))); }
    }
    uint32_t read_hex4() {
        uint32_t cp = 0;
        for (int i = 0; i < 4; ++i) { int d = hex(take()); if (d < 0) throw std::runtime_error("invalid JSON unicode escape"); cp = (cp << 4) | static_cast<uint32_t>(d); }
        return cp;
    }
    std::string read_string(bool& truncated) {
        if (take() != '"') throw std::runtime_error("expected JSON string");
        // Tokens are only used for schema keys/methods/ignored values; a hard
        // cap prevents an attacker-controlled string from becoming an allocation.
        constexpr size_t kMaxStringBytes = 256;
        std::string out;
        auto append = [&](char value) {
            if (out.size() < kMaxStringBytes) out.push_back(value);
            else truncated = true;
        };
        auto append_cp = [&](uint32_t cp) {
            const size_t bytes = cp <= 0x7f ? 1 : cp <= 0x7ff ? 2 : cp <= 0xffff ? 3 : 4;
            if (out.size() + bytes <= kMaxStringBytes) append_utf8(out, cp);
            else truncated = true;
        };
        while (true) {
            int c = take();
            if (c == EOF) throw std::runtime_error("unterminated JSON string");
            if (c == '"') break;
            if (c < 0x20) throw std::runtime_error("control character in JSON string");
            if (c != '\\') {
                if (c >= 0x80) {
                    int count = (c >= 0xc2 && c <= 0xdf) ? 1 : (c >= 0xe0 && c <= 0xef) ? 2 : (c >= 0xf0 && c <= 0xf4) ? 3 : -1;
                    if (count < 0) throw std::runtime_error("invalid UTF-8 in JSON string");
                    append(static_cast<char>(c));
                    for (int i = 0; i < count; ++i) {
                        int continuation = take();
                        int low = 0x80, high = 0xbf;
                        if (i == 0 && c == 0xe0) low = 0xa0;
                        if (i == 0 && c == 0xed) high = 0x9f;
                        if (i == 0 && c == 0xf0) low = 0x90;
                        if (i == 0 && c == 0xf4) high = 0x8f;
                        if (continuation < low || continuation > high) throw std::runtime_error("invalid UTF-8 continuation in JSON string");
                        append(static_cast<char>(continuation));
                    }
                } else append(static_cast<char>(c));
                continue;
            }
            int e = take();
            switch (e) {
                case '"': case '\\': case '/': append(static_cast<char>(e)); break;
                case 'b': append('\b'); break; case 'f': append('\f'); break; case 'n': append('\n'); break; case 'r': append('\r'); break; case 't': append('\t'); break;
                case 'u': {
                    uint32_t cp = read_hex4();
                    if (cp >= 0xd800 && cp <= 0xdbff) {
                        if (take() != '\\' || take() != 'u') throw std::runtime_error("invalid JSON surrogate pair");
                        uint32_t low = read_hex4();
                        if (low < 0xdc00 || low > 0xdfff) throw std::runtime_error("invalid JSON surrogate pair");
                        cp = 0x10000 + ((cp - 0xd800) << 10) + (low - 0xdc00);
                    } else if (cp >= 0xdc00 && cp <= 0xdfff) throw std::runtime_error("invalid JSON surrogate pair");
                    append_cp(cp); break;
                }
                default: throw std::runtime_error("invalid JSON string escape");
            }
        }
        return out;
    }
    std::string read_number() {
        std::string out;
        auto consume_digits = [&]() {
            size_t count = 0;
            while (peek() >= '0' && peek() <= '9') {
                if (out.size() >= 128) throw std::runtime_error("JSON number exceeds 128-byte parser limit");
                out.push_back(static_cast<char>(take())); ++count;
            }
            return count;
        };
        if (peek() == '-') out.push_back(static_cast<char>(take()));
        if (peek() == '0') {
            out.push_back(static_cast<char>(take()));
            if (peek() >= '0' && peek() <= '9') throw std::runtime_error("leading zero in JSON number");
        } else if (peek() >= '1' && peek() <= '9') consume_digits();
        else throw std::runtime_error("invalid JSON number");
        if (peek() == '.') {
            out.push_back(static_cast<char>(take()));
            if (consume_digits() == 0) throw std::runtime_error("invalid JSON fraction");
        }
        if (peek() == 'e' || peek() == 'E') {
            out.push_back(static_cast<char>(take()));
            if (peek() == '+' || peek() == '-') out.push_back(static_cast<char>(take()));
            if (consume_digits() == 0) throw std::runtime_error("invalid JSON exponent");
        }
        return out;
    }
    void read_literal(const char* literal) {
        for (const char* p = literal; *p; ++p) if (take() != *p) throw std::runtime_error("invalid JSON literal");
    }
};

inline int json_nonnegative_int(const JsonScanner::Token& t, const char* label) {
    if (t.kind != 'n' || t.value.empty() || t.value[0] == '-') throw std::runtime_error(std::string(label) + " must be a non-negative integer");
    if (t.value.size() > 1 && t.value[0] == '0') throw std::runtime_error(std::string(label) + " is not a canonical integer");
    uint64_t value = 0;
    for (char c : t.value) {
        if (c < '0' || c > '9') throw std::runtime_error(std::string(label) + " must be an integer");
        const unsigned digit = static_cast<unsigned>(c - '0');
        if (value > (static_cast<uint64_t>(std::numeric_limits<int>::max()) - digit) / 10)
            throw std::runtime_error(std::string(label) + " is outside supported range");
        value = value * 10 + digit;
    }
    return static_cast<int>(value);
}

inline uint64_t json_uint64(const JsonScanner::Token& t, const char* label) {
    if (t.kind != 'n' || t.value.empty() || t.value[0] == '-') throw std::runtime_error(std::string(label) + " must be a non-negative integer");
    uint64_t value = 0;
    for (char c : t.value) {
        if (c < '0' || c > '9') throw std::runtime_error(std::string(label) + " must be an integer");
        const unsigned digit = static_cast<unsigned>(c - '0');
        if (value > (std::numeric_limits<uint64_t>::max() - digit) / 10) throw std::runtime_error(std::string(label) + " exceeds uint64 range");
        value = value * 10 + digit;
    }
    return value;
}

inline JsonGraph load_json_graph(const std::string& path) {
    constexpr int kHardMaxVertices = 2'000'000;
    constexpr size_t kHardMaxEdges = 10'000'000;
    auto configured_limit = [](const char* name, uint64_t fallback, uint64_t hard_max) {
        const char* raw = std::getenv(name);
        if (!raw || !*raw) return fallback;
        uint64_t value = 0;
        for (const char* p = raw; *p; ++p) {
            if (*p < '0' || *p > '9') throw std::runtime_error(std::string(name) + " must be a positive integer");
            const uint64_t digit = static_cast<uint64_t>(*p - '0');
            if (value > (hard_max - digit) / 10) throw std::runtime_error(std::string(name) + " exceeds hard safety maximum");
            value = value * 10 + digit;
        }
        if (value == 0) throw std::runtime_error(std::string(name) + " must be positive");
        return value;
    };
    const int kMaxVertices = static_cast<int>(configured_limit("PREDATOR_NATIVE_MAX_VERTICES", 500'000, kHardMaxVertices));
    const size_t kMaxEdges = static_cast<size_t>(configured_limit("PREDATOR_NATIVE_MAX_EDGES", 3'000'000, kHardMaxEdges));
    JsonScanner scanner(path);
    JsonGraph result;
    // Place the edge spool beside the staged JSON, so the API's staging-volume
    // budget accounts for both files. mkstemp gives an exclusive 0600 file.
    std::string spool_template = path + ".edges.XXXXXX";
    const int spool_fd = ::mkstemp(&spool_template[0]);
    if (spool_fd < 0) throw std::runtime_error("cannot create native edge spool");
    if (::unlink(spool_template.c_str()) != 0) {
        ::close(spool_fd);
        throw std::runtime_error("cannot unlink native edge spool name");
    }
    FILE* spool_file = ::fdopen(spool_fd, "w+b");
    if (!spool_file) {
        ::close(spool_fd);
        throw std::runtime_error("cannot open native edge spool");
    }
    result.edge_spool = std::shared_ptr<FILE>(spool_file, [](FILE* file) { if (file) std::fclose(file); });
    auto parse_edges = [&](JsonScanner::Token token) {
        if (token.kind != '[') throw std::runtime_error("graph.edges must be an array");
        token = scanner.next();
        if (token.kind == ']') return;
        while (true) {
            if (token.kind != '[') throw std::runtime_error("each graph edge must be a two-integer array");
            auto u = json_nonnegative_int(scanner.next(), "edge endpoint");
            if (scanner.next().kind != ',') throw std::runtime_error("each graph edge must have exactly two endpoints");
            auto v = json_nonnegative_int(scanner.next(), "edge endpoint");
            auto close = scanner.next();
            if (close.kind != ']') throw std::runtime_error("each graph edge must have exactly two endpoints");
            if (result.m >= kMaxEdges) throw std::runtime_error("edge count exceeds native limit");
            if (u == v) throw std::runtime_error("self-loop edges are not supported by MORPH JSON mode");
            if (u > v) std::swap(u, v);
            const uint32_t pair[2] = {static_cast<uint32_t>(u), static_cast<uint32_t>(v)};
            if (std::fwrite(pair, sizeof(pair), 1, result.edge_spool.get()) != 1)
                throw std::runtime_error("failed to write native edge spool");
            ++result.m;
            token = scanner.next();
            if (token.kind == ']') break;
            if (token.kind != ',') throw std::runtime_error("malformed graph.edges separator");
            token = scanner.next();
        }
    };
    auto parse_graph = [&](JsonScanner::Token token) {
        if (token.kind != '{') throw std::runtime_error("graph must be an object");
        bool got_n = false, got_edges = false, got_directed = false;
        token = scanner.next();
        std::unordered_set<std::string> keys;
        if (token.kind != '}') {
            while (true) {
                if (keys.size() >= 64) throw std::runtime_error("graph object exceeds 64-member parser limit");
                if (token.kind != 's' || token.truncated || scanner.next().kind != ':') throw std::runtime_error("malformed graph object key");
                std::string key = token.value;
                if (!keys.insert(key).second) throw std::runtime_error("duplicate graph object key");
                JsonScanner::Token value = scanner.next();
                if (key == "n") {
                    result.n = json_nonnegative_int(value, "graph.n");
                    if (result.n < 1 || result.n > kMaxVertices) throw std::runtime_error("graph.n outside native vertex limits");
                    got_n = true;
                } else if (key == "edges") {
                    if (got_edges) throw std::runtime_error("duplicate graph.edges");
                    parse_edges(value); got_edges = true;
                } else if (key == "directed") {
                    if (value.kind != 'b') throw std::runtime_error("graph.directed must be a boolean");
                    result.directed = value.value == "true"; got_directed = true;
                } else scanner.skip_value(value);
                token = scanner.next();
                if (token.kind == '}') break;
                if (token.kind != ',') throw std::runtime_error("malformed graph object separator");
                token = scanner.next();
            }
        }
        if (!got_n || !got_edges) throw std::runtime_error("graph must contain graph.n and graph.edges");
    };

    auto token = scanner.next();
    if (token.kind != '{') throw std::runtime_error("request JSON must be an object");
    token = scanner.next();
    bool graph_found = false, got_method = false, got_budget = false, got_seed = false;
    std::unordered_set<std::string> root_keys;
    if (token.kind != '}') {
        while (true) {
            if (root_keys.size() >= 64) throw std::runtime_error("request object exceeds 64-member parser limit");
            if (token.kind != 's' || token.truncated || scanner.next().kind != ':') throw std::runtime_error("malformed request object key");
            std::string key = token.value;
            if (!root_keys.insert(key).second) throw std::runtime_error("duplicate request JSON key");
            auto value = scanner.next();
            if (key == "graph") {
                if (graph_found) throw std::runtime_error("duplicate graph object");
                parse_graph(value); graph_found = true;
            } else if (key == "method") {
                if (got_method || value.kind != 's' || value.truncated) throw std::runtime_error("method must be a unique bounded string");
                result.method = value.value; got_method = true;
            } else if (key == "budget_ms") {
                if (got_budget) throw std::runtime_error("duplicate budget_ms");
                result.budget_ms = json_nonnegative_int(value, "budget_ms"); got_budget = true;
            } else if (key == "seed") {
                if (got_seed) throw std::runtime_error("duplicate seed");
                result.seed = json_uint64(value, "seed"); got_seed = true;
            } else scanner.skip_value(value);
            token = scanner.next();
            if (token.kind == '}') break;
            if (token.kind != ',') throw std::runtime_error("malformed request object separator");
            token = scanner.next();
        }
    }
    if (scanner.next().kind != 'e') throw std::runtime_error("trailing content after request JSON");
    if (!graph_found || result.n < 1) throw std::runtime_error("request must contain graph.n >= 1 and graph.edges");
    if (result.n > kMaxVertices) throw std::runtime_error("graph.n exceeds native vertex limit");
    if (!got_method || result.method != "morph") throw std::runtime_error("native JSON endpoint requires method=morph");
    if (result.budget_ms < 1 || result.budget_ms > 600'000) throw std::runtime_error("budget_ms outside [1, 600000]");
    if (result.directed) throw std::runtime_error("directed graphs are not supported by MORPH JSON mode");
    // Validate endpoints and calculate CSR degrees after all graph fields have
    // been read, so graph.n and graph.edges may appear in either order.
    result.degree.assign(static_cast<size_t>(result.n), 0);
    if (std::fflush(result.edge_spool.get()) != 0 || std::fseek(result.edge_spool.get(), 0, SEEK_SET) != 0)
        throw std::runtime_error("cannot rewind native edge spool");
    uint32_t pair[2];
    for (size_t i = 0; i < result.m; ++i) {
        if (std::fread(pair, sizeof(pair), 1, result.edge_spool.get()) != 1)
            throw std::runtime_error("truncated native edge spool");
        if (pair[0] >= static_cast<uint32_t>(result.n) || pair[1] >= static_cast<uint32_t>(result.n))
            throw std::runtime_error("edge endpoint outside graph.n");
        if (result.degree[pair[0]] == std::numeric_limits<int>::max() || result.degree[pair[1]] == std::numeric_limits<int>::max())
            throw std::runtime_error("vertex degree exceeds supported range");
        ++result.degree[pair[0]];
        ++result.degree[pair[1]];
    }
    if (std::fseek(result.edge_spool.get(), 0, SEEK_SET) != 0)
        throw std::runtime_error("cannot rewind native edge spool");
    return result;
}
