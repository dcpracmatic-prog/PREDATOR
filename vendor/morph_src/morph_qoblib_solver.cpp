
#include <bits/stdc++.h>

using namespace std;

struct Graph {
    int n;
    vector<int> off;
    vector<int> adj;
    vector<int> deg;
};

struct Solution {
    int size = 0;
    vector<uint8_t> x;
};

static uint64_t splitmix64(uint64_t x)
{
    x += 0x9e3779b97f4a7c15ULL;

    x = (x ^ (x >> 30))
        * 0xbf58476d1ce4e5b9ULL;

    x = (x ^ (x >> 27))
        * 0x94d049bb133111ebULL;

    return x ^ (x >> 31);
}

static Graph load_graph(const string& file)
{
    ifstream in(file);

    if (!in)
        throw runtime_error("cannot open graph");

    string tag;
    string tmp;

    int n = 0;
    int m = 0;

    vector<pair<int,int>> edges;

    while (in >> tag) {

        if (tag == "c") {
            getline(in, tmp);
            continue;
        }

        if (tag == "p") {

            in >> tmp >> n >> m;

            edges.reserve(m);
            continue;
        }

        if (tag == "e") {

            int a, b;
            in >> a >> b;

            --a;
            --b;

            if (
                a >= 0 &&
                b >= 0 &&
                a < n &&
                b < n &&
                a != b
            ) {
                edges.emplace_back(a,b);
            }
        }
    }

    Graph g;

    g.n = n;

    g.deg.assign(n, 0);

    g.off.assign(n + 1, 0);

    for (auto [a,b] : edges) {

        g.deg[a]++;
        g.deg[b]++;

        g.off[a + 1]++;
        g.off[b + 1]++;
    }

    for (int i = 0; i < n; ++i)
        g.off[i + 1] += g.off[i];

    g.adj.resize(g.off[n]);

    vector<int> cursor = g.off;

    for (auto [a,b] : edges) {

        g.adj[cursor[a]++] = b;
        g.adj[cursor[b]++] = a;
    }

    return g;
}

static bool valid(
    const Graph& g,
    const Solution& s
)
{
    for (int v = 0; v < g.n; ++v) {

        if (!s.x[v])
            continue;

        for (
            int p = g.off[v];
            p < g.off[v+1];
            ++p
        ) {

            int u = g.adj[p];

            if (s.x[u])
                return false;
        }
    }

    return true;
}


// ------------------------------------------------------------
// DEGREE GREEDY
// ------------------------------------------------------------

static vector<int> degree_order(
    const Graph& g,
    uint64_t seed
)
{
    vector<int> order(g.n);

    iota(
        order.begin(),
        order.end(),
        0
    );

    sort(
        order.begin(),
        order.end(),
        [&](int a, int b) {

            if (g.deg[a] != g.deg[b])
                return g.deg[a] < g.deg[b];

            return
                splitmix64(seed + a)
                <
                splitmix64(seed + b);
        }
    );

    return order;
}

static Solution greedy(
    const Graph& g,
    const vector<int>& order
)
{
    Solution s;

    s.x.assign(g.n, 0);

    for (int v : order) {

        bool ok = true;

        for (
            int p = g.off[v];
            p < g.off[v+1];
            ++p
        ) {

            if (s.x[g.adj[p]]) {
                ok = false;
                break;
            }
        }

        if (ok) {
            s.x[v] = 1;
            s.size++;
        }
    }

    return s;
}


// ------------------------------------------------------------
// MORPH v1.5 — RESIDUAL DEGREE
// ------------------------------------------------------------

struct HeapNode {

    int degree;
    int vertex;

    bool operator>(
        const HeapNode& other
    ) const {

        if (degree != other.degree)
            return degree > other.degree;

        return vertex > other.vertex;
    }
};

static Solution minres(
    const Graph& g,
    uint64_t seed
)
{
    Solution s;

    s.x.assign(g.n, 0);

    vector<uint8_t> active(g.n, 1);

    vector<int> residual = g.deg;

    priority_queue<
        HeapNode,
        vector<HeapNode>,
        greater<HeapNode>
    > heap;

    for (int v = 0; v < g.n; ++v) {

        int tie =
            (int)(splitmix64(seed + v) & 0xffff);

        heap.push({
            residual[v] * 1000000 + tie,
            v
        });
    }

    int remaining = g.n;

    while (
        remaining > 0 &&
        !heap.empty()
    ) {

        auto h = heap.top();
        heap.pop();

        int v = h.vertex;

        if (!active[v])
            continue;

        int current_key =
            residual[v] * 1000000
            +
            (int)(splitmix64(seed + v) & 0xffff);

        if (h.degree != current_key)
            continue;

        // Select v into MIS.
        s.x[v] = 1;
        s.size++;

        // Remove v.
        if (active[v]) {
            active[v] = 0;
            remaining--;
        }

        // Remove all neighbors.
        for (
            int p = g.off[v];
            p < g.off[v+1];
            ++p
        ) {

            int u = g.adj[p];

            if (!active[u])
                continue;

            active[u] = 0;
            remaining--;

            // Their removal changes residual degree
            // of their active neighbors.
            for (
                int q = g.off[u];
                q < g.off[u+1];
                ++q
            ) {

                int w = g.adj[q];

                if (!active[w])
                    continue;

                residual[w]--;

                int key =
                    residual[w] * 1000000
                    +
                    (int)(
                        splitmix64(seed + w)
                        & 0xffff
                    );

                heap.push({
                    key,
                    w
                });
            }
        }
    }

    return s;
}


// ------------------------------------------------------------
// 1 -> 2 LOCAL IMPROVEMENT
// ------------------------------------------------------------

// Correct 1->2 local improvement. A valid exchange removes one selected
// vertex u and adds two nonadjacent vertices v,w whose only selected neighbor
// is u. The previous implementation searched w only among neighbors of v,
// making the non-adjacency check reject every exchange.
static void improve_1_to_2(const Graph& g, Solution& s)
{
    vector<vector<int>> candidates_by_u(g.n);
    for (int v = 0; v < g.n; ++v) {
        if (s.x[v]) continue;
        int selected = -1, count = 0;
        for (int p = g.off[v]; p < g.off[v+1]; ++p) {
            int u = g.adj[p];
            if (s.x[u]) { selected = u; ++count; }
            if (count > 1) break;
        }
        if (count == 1) candidates_by_u[selected].push_back(v);
    }

    vector<uint8_t> adjacent(g.n, 0);
    for (int u = 0; u < g.n; ++u) {
        const auto& candidates = candidates_by_u[u];
        if (candidates.size() < 2) continue;
        for (int v : candidates) {
            for (int p = g.off[v]; p < g.off[v+1]; ++p)
                adjacent[g.adj[p]] = 1;
            for (int w : candidates) {
                if (v != w && !adjacent[w]) {
                    s.x[u] = 0;
                    s.x[v] = 1;
                    s.x[w] = 1;
                    ++s.size;
                    return;
                }
            }
            for (int p = g.off[v]; p < g.off[v+1]; ++p)
                adjacent[g.adj[p]] = 0;
        }
    }
}

// ------------------------------------------------------------
// TIME-BUDGETED MORPH
// ------------------------------------------------------------

static Solution morph(
    const Graph& g,
    uint64_t seed,
    int budget_ms
)
{
    auto start =
        chrono::steady_clock::now();

    auto deadline =
        start +
        chrono::milliseconds(budget_ms);

    Solution best =
        minres(g, seed);

    improve_1_to_2(g, best);

    uint64_t iteration = 1;

    while (
        chrono::steady_clock::now()
        <
        deadline
    ) {

        Solution candidate =
            minres(
                g,
                seed +
                iteration * 0x9e3779b97f4a7c15ULL
            );

        improve_1_to_2(
            g,
            candidate
        );

        if (
            candidate.size
            >
            best.size
        ) {
            best =
                std::move(candidate);
        }

        iteration++;
    }

    return best;
}


// ------------------------------------------------------------
// MAIN
// ------------------------------------------------------------

int main(
    int argc,
    char** argv
)
{
    if (argc < 5) {

        cerr
            << "usage: morph_v15_fair "
            << "<graph> <method> <budget_ms> <seed>\n";

        return 2;
    }

    string file = argv[1];
    string method = argv[2];

    int budget_ms =
        stoi(argv[3]);

    uint64_t seed =
        stoull(argv[4]);

    Graph g =
        load_graph(file);

    auto t0 =
        chrono::steady_clock::now();

    Solution s;

    if (method == "degree") {

        s =
            greedy(
                g,
                degree_order(g, 0)
            );
    }

    else if (method == "random") {

        s =
            greedy(
                g,
                degree_order(g, seed)
            );
    }

    else if (method == "local") {

        s =
            greedy(
                g,
                degree_order(g, seed)
            );

        improve_1_to_2(
            g,
            s
        );
    }

    else if (method == "morph") {

        s =
            morph(
                g,
                seed,
                budget_ms
            );
    }

    else {

        cerr << "unknown method\n";
        return 3;
    }

    auto t1 =
        chrono::steady_clock::now();

    double wall_ms =
        chrono::duration<double, milli>(
            t1 - t0
        ).count();

    cout
        << g.n
        << ","
        << g.adj.size() / 2
        << ","
        << s.size
        << ","
        << wall_ms
        << ","
        << (valid(g, s) ? 1 : 0)
        << "\n";

    return 0;
}
