#include <bits/stdc++.h>
#include <sys/resource.h>
using namespace std;
struct Graph{int n; vector<int> off, adj; vector<int> deg;};
static uint64_t splitmix64(uint64_t x){x+=0x9e3779b97f4a7c15ULL; x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL; x=(x^(x>>27))*0x94d049bb133111ebULL; return x^(x>>31);} 

Graph load_gph(const string& path){ifstream in(path);string t;int n=0,m=0;vector<pair<int,int>> e;while(in>>t){if(t=="p"){string z;in>>z>>n>>m;e.reserve(m);}else if(t=="e"){int u,v;in>>u>>v;--u;--v;e.push_back({u,v});}}Graph g;g.n=n;g.deg.assign(n,0);g.off.assign(n+1,0);for(auto [u,v]:e){g.deg[u]++;g.deg[v]++;g.off[u+1]++;g.off[v+1]++;}for(int i=0;i<n;i++)g.off[i+1]+=g.off[i];g.adj.resize(g.off[n]);auto cur=g.off;for(auto [u,v]:e){g.adj[cur[u]++]=v;g.adj[cur[v]++]=u;}return g;}

Graph ba_graph(int n,int m0,int m, uint64_t seed){
    vector<pair<int,int>> edges; edges.reserve((size_t)n*m);
    vector<int> deg(n); vector<int> targets; targets.reserve((size_t)n*m*2);
    mt19937_64 rng(seed);
    for(int i=0;i<m0;i++) for(int j=i+1;j<m0;j++){edges.push_back({i,j});deg[i]++;deg[j]++;targets.push_back(i);targets.push_back(j);} 
    for(int v=m0;v<n;v++){
        unordered_set<int> chosen; chosen.reserve(m*2);
        while((int)chosen.size()<m){ int u=targets[rng()%targets.size()]; if(u!=v) chosen.insert(u); }
        for(int u:chosen){edges.push_back({u,v});deg[u]++;deg[v]++;targets.push_back(u);targets.push_back(v);} }
    Graph g; g.n=n; g.deg=deg; g.off.assign(n+1,0); for(auto [u,v]:edges){g.off[u+1]++;g.off[v+1]++;} for(int i=0;i<n;i++)g.off[i+1]+=g.off[i]; g.adj.resize(g.off[n]); vector<int> cur=g.off; for(auto [u,v]:edges){g.adj[cur[u]++]=v;g.adj[cur[v]++]=u;} return g;
}
struct Sol{int size=0; vector<uint8_t> x;};
Sol greedy(const Graph&g, const vector<int>&order){ Sol s; s.x.assign(g.n,0); for(int v:order){bool ok=1; for(int p=g.off[v];p<g.off[v+1];p++) if(s.x[g.adj[p]]){ok=0;break;} if(ok){s.x[v]=1;s.size++;}} return s; }
vector<int> degree_order(const Graph&g){vector<int> o(g.n); iota(o.begin(),o.end(),0); stable_sort(o.begin(),o.end(),[&](int a,int b){if(g.deg[a]!=g.deg[b])return g.deg[a]<g.deg[b];return a<b;});return o;}
vector<int> random_degree_order(const Graph&g,uint64_t seed){vector<int> o(g.n);iota(o.begin(),o.end(),0); vector<uint32_t> key(g.n);for(int i=0;i<g.n;i++)key[i]=(uint32_t)splitmix64(seed+i); stable_sort(o.begin(),o.end(),[&](int a,int b){uint64_t sa=((uint64_t)g.deg[a]<<32)|key[a];uint64_t sb=((uint64_t)g.deg[b]<<32)|key[b];return sa<sb;});return o;}
// Local search: attempt a valid 1->2 exchange. Both unselected vertices must
// have exactly one selected neighbor (the same u), and must not be adjacent.
void improve12(const Graph& g, Sol& s, int maxv=5000) {
    vector<int> candidates;
    candidates.reserve(min(maxv, g.n));

    for (int v = 0; v < g.n; ++v) {
        if (s.x[v]) continue;
        int selected = -1, count = 0;
        for (int p = g.off[v]; p < g.off[v+1]; ++p) {
            int u = g.adj[p];
            if (s.x[u]) { selected = u; ++count; }
            if (count > 1) break;
        }
        if (count == 1) candidates.push_back(v);
    }
    if ((int)candidates.size() > maxv) candidates.resize(maxv);

    vector<vector<int>> by_selected(g.n);
    for (int v : candidates) {
        int u = -1, count = 0;
        for (int p = g.off[v]; p < g.off[v+1]; ++p) {
            int z = g.adj[p];
            if (s.x[z]) { u = z; ++count; }
        }
        if (count == 1) by_selected[u].push_back(v);
    }

    vector<uint8_t> adjacent(g.n, 0);
    for (int u = 0; u < g.n; ++u) {
        if (by_selected[u].size() < 2) continue;
        for (int v : by_selected[u]) {
            for (int p = g.off[v]; p < g.off[v+1]; ++p)
                adjacent[g.adj[p]] = 1;
            for (int w : by_selected[u]) {
                if (v == w || adjacent[w]) continue;
                s.x[u] = 0;
                s.x[v] = 1;
                s.x[w] = 1;
                ++s.size;
                return; // One exchange per call; caller may invoke again.
            }
            for (int p = g.off[v]; p < g.off[v+1]; ++p)
                adjacent[g.adj[p]] = 0;
        }
    }
}
Sol morph(const Graph&g, uint64_t seed, int ms){
 auto start=chrono::steady_clock::now(); auto deadline=start+chrono::milliseconds(ms);
 auto base=degree_order(g); Sol best=greedy(g,base);
 mt19937_64 rng(seed); vector<uint8_t> state(g.n), removed(g.n); vector<int> order(g.n), sel, pool;
 int iter=0;
 while(chrono::steady_clock::now()<deadline){
   uint64_t r=splitmix64(seed+iter++);
   const vector<int>* ord=&base; if((iter&3)!=0){order=random_degree_order(g,r);ord=&order;}
   Sol s=greedy(g,*ord);
   // perturb: remove a small deterministic sample from selected solution, then repair with residual low-degree ordering.
   if(s.size>100){int rem=max(1,min(s.size/50,2000)); sel.clear(); for(int v=0;v<g.n;v++)if(s.x[v])sel.push_back(v); for(int j=0;j<rem;j++){int k=(int)(splitmix64(r+j)%sel.size()); swap(sel[k],sel.back()); int v=sel.back();sel.pop_back();s.x[v]=0;s.size--;}}
   // Repair: scan vertices in randomized degree order, cheap and cache-friendly.
   for(int v:*ord) if(!s.x[v]){bool ok=1;for(int p=g.off[v];p<g.off[v+1];p++)if(s.x[g.adj[p]]){ok=0;break;}if(ok){s.x[v]=1;s.size++;}}
   if(s.size>best.size)best=s;
 }
 improve12(g,best);
 return best;
}

Sol minres(const Graph&g){
 int n=g.n; vector<int> rd=g.deg; vector<uint8_t> alive(n,1), x(n,0); priority_queue<pair<int,int>, vector<pair<int,int>>, greater<pair<int,int>>> pq; for(int i=0;i<n;i++)pq.push({rd[i],i}); int sz=0;
 while(!pq.empty()){
   auto [d,v]=pq.top();pq.pop(); if(!alive[v]||d!=rd[v])continue;
   x[v]=1;sz++; alive[v]=0;
   for(int p=g.off[v];p<g.off[v+1];p++){int u=g.adj[p]; if(!alive[u])continue; alive[u]=0; for(int q=g.off[u];q<g.off[u+1];q++){int w=g.adj[q];if(alive[w]){rd[w]--;pq.push({rd[w],w});}}}
 }
 return Sol{sz,move(x)};
}

bool valid(const Graph&g,const Sol&s){for(int v=0;v<g.n;v++)if(s.x[v])for(int p=g.off[v];p<g.off[v+1];p++)if(s.x[g.adj[p]])return false;return true;}
int main(int argc,char**argv){
 string src=argc>1?argv[1]:"ba"; int n=0,ms=100;uint64_t seed=1;Graph g;
 if(src=="ba"){n=argc>2?atoi(argv[2]):65536;ms=argc>3?atoi(argv[3]):100;seed=argc>4?strtoull(argv[4],0,10):1;g=ba_graph(n,5,5,seed);}else{ms=argc>2?atoi(argv[2]):100;seed=argc>3?strtoull(argv[3],0,10):1;g=load_gph(src);n=g.n;}
 auto t0=chrono::steady_clock::now();auto d=degree_order(g);auto s0=greedy(g,d);auto rg=random_degree_order(g,seed+99);auto s1=greedy(g,rg);auto s2=s1;improve12(g,s2);auto s3=minres(g);auto t1=chrono::steady_clock::now();struct rusage ru{};getrusage(RUSAGE_SELF,&ru);double rss=ru.ru_maxrss/1024.0;cout<<src<<","<<n<<","<<g.adj.size()/2<<","<<s0.size<<","<<s1.size<<","<<s2.size<<","<<s3.size<<","<<rss<<","<<chrono::duration<double,milli>(t1-t0).count()<<","<<valid(g,s0)<<valid(g,s1)<<valid(g,s2)<<valid(g,s3)<<"\n";
}
