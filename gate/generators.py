"""Code-computed GATE question families. Every answer is computed here (never by an LLM), so these need no API call and
no verification: they are the zero-cost / zero-risk part of every paper and the fallback when the API budget is exhausted.
Each family(marks) -> question dict:  type mcq|msq|nat, question, context, code, figure, options{a..d}, answer, explanation.
answer: mcq 'b' | msq ['a','c'] | nat [lo, hi]."""
import math, random, itertools, heapq
from functools import lru_cache

# ── helpers ─────────────────────────────────────────────────────────────────
def _fmt(v):
    return str(int(v)) if float(v).is_integer() else ("%.3f" % v).rstrip("0").rstrip(".")
def _nat(v, tol=0.0): return [round(v - tol, 4), round(v + tol, 4)]
def _mcq(correct, wrong, rnd=random):
    """correct + list of candidate distractors (strings) -> options a..d, answer letter"""
    c = str(correct); pool = [w for w in dict.fromkeys(str(x) for x in wrong) if w != c]
    rnd.shuffle(pool); opts = [c] + pool[:3]
    while len(opts) < 4: opts.append(opts[-1] + "0")
    rnd.shuffle(opts)
    return dict(zip("abcd", opts)), "abcd"[opts.index(c)]
def _num_mcq(v, marks=1):
    v = int(v) if float(v).is_integer() else round(v, 2)
    d = sorted({v + 1, v - 1, v + 2, v * 2, max(v - 2, 0), v + 5, v // 2 if isinstance(v, int) else v}, key=lambda x: abs(x - v))
    return _mcq(_fmt(v), [_fmt(x) for x in d if x != v and x >= 0 or x == 0])
def _circle(nodes):
    r0 = random.uniform(0, math.pi)
    return {n: [round(50 + 40 * math.cos(r0 + 2 * math.pi * i / len(nodes)), 1), round(50 + 40 * math.sin(r0 + 2 * math.pi * i / len(nodes)), 1)] for i, n in enumerate(nodes)}
def _graph(nv=6, extra=4, wmax=12):
    nodes = list("ABCDEFGH"[:nv]); edges = {}
    order = nodes[:]; random.shuffle(order)
    for i in range(1, nv):                       # random spanning tree first => connected
        a, b = order[i], order[random.randrange(i)]
        edges[tuple(sorted((a, b)))] = random.randint(1, wmax)
    for _ in range(extra):
        a, b = random.sample(nodes, 2); edges.setdefault(tuple(sorted((a, b))), random.randint(1, wmax))
    return nodes, edges
def _gfig(nodes, edges):
    return {"kind": "graph", "directed": False, "nodes": nodes, "pos": _circle(nodes), "edges": [[a, b, w] for (a, b), w in edges.items()]}

# ── ALGORITHMS ───────────────────────────────────────────────────────────────
def algo_dijkstra(marks):
    nodes, edges = _graph(6, 4)
    adj = {n: [] for n in nodes}
    for (a, b), w in edges.items(): adj[a].append((b, w)); adj[b].append((a, w))
    s, t = "A", random.choice(nodes[3:]); dist = {n: 10**9 for n in nodes}; dist[s] = 0; pq = [(0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue
        for v, w in adj[u]:
            if d + w < dist[v]: dist[v] = d + w; heapq.heappush(pq, (d + w, v))
    q = dict(type="nat", question=f"Consider the undirected weighted graph shown in the figure. Using Dijkstra's algorithm, the length of the shortest path from vertex {s} to vertex {t} is ______.",
             figure=_gfig(nodes, edges), answer=_nat(dist[t]), explanation=f"Dijkstra from {s}: dist({t}) = {dist[t]}.")
    if random.random() < .4:
        o, a = _num_mcq(dist[t]); q.update(type="mcq", options=o, answer=a, question=q["question"].replace("is ______.", "is"))
    return q
def algo_mst(marks):
    nodes, edges = _graph(6, 5, 15)
    ws = sorted(edges.items(), key=lambda x: x[1]); par = {n: n for n in nodes}
    def f(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    tot = 0
    for (a, b), w in ws:
        if f(a) != f(b): par[f(a)] = f(b); tot += w
    if random.random() < .5:
        q = dict(type="nat", question="For the connected undirected weighted graph in the figure, the weight of a minimum spanning tree is ______.", answer=_nat(tot))
    else:
        o, a = _num_mcq(tot); q = dict(type="mcq", question="The total weight of a minimum spanning tree of the graph shown in the figure is", options=o, answer=a)
    q.update(figure=_gfig(nodes, edges), explanation=f"Kruskal picks the cheapest edges that create no cycle; total = {tot}.")
    return q
def algo_hash(marks):
    m = random.choice([7, 9, 10, 11]); keys = random.sample(range(10, 99), 6); tab = [None] * m; probes = 0
    for k in keys:
        i, j = k % m, 0
        while tab[(i + j) % m] is not None: j += 1
        tab[(i + j) % m] = k; probes += j + 1
    slot = random.choice(keys)
    q = dict(type="nat", question=f"A hash table with {m} slots (indexed 0 to {m-1}) uses the hash function h(k) = k mod {m} and linear probing. The keys {', '.join(map(str, keys))} are inserted in this order into an initially empty table. The slot index at which the key {slot} finally resides is ______.",
             answer=_nat(tab.index(slot)), explanation=f"Table after all insertions: {tab}.")
    return q
def algo_recurrence(marks):
    a, b, k, ans = random.choice([(2, 2, 1, "Θ(n log n)"), (4, 2, 1, "Θ(n²)"), (2, 2, 2, "Θ(n²)"), (3, 3, 1, "Θ(n log n)"), (1, 2, 0, "Θ(log n)"), (8, 2, 2, "Θ(n³)"), (2, 4, 1, "Θ(n)"), (9, 3, 1, "Θ(n²)"), (2, 2, 0, "Θ(n)")])
    fn = {0: "1", 1: "n", 2: "n²"}[k]
    o, c = _mcq(ans, [x for x in ["Θ(n)", "Θ(n log n)", "Θ(n²)", "Θ(n³)", "Θ(log n)", "Θ(n² log n)"] if x != ans])
    coef = "" if a == 1 else str(a)
    return dict(type="mcq", question=f"The solution of the recurrence T(n) = {coef}T(n/{b}) + {fn}, with T(1) = 1, is", options=o, answer=c,
                explanation=f"Master theorem: n^(log_{b} {a}) = n^{_fmt(round(math.log(a, b), 3))} compared with f(n) = {fn}.")

# ── PROGRAMMING & DATA STRUCTURES ────────────────────────────────────────────
class _N:
    def __init__(s, v): s.v, s.l, s.r = v, None, None
def _ins(t, v):
    if not t: return _N(v)
    if v < t.v: t.l = _ins(t.l, v)
    else: t.r = _ins(t.r, v)
    return t
def _tree(t): return None if not t else {"v": t.v, "l": _tree(t.l), "r": _tree(t.r)}
def _height(t): return -1 if not t else 1 + max(_height(t.l), _height(t.r))
def _walk(t, o):
    if not t: return []
    return {"pre": [t.v] + _walk(t.l, o) + _walk(t.r, o), "in": _walk(t.l, o) + [t.v] + _walk(t.r, o), "post": _walk(t.l, o) + _walk(t.r, o) + [t.v]}[o]
def pds_bst(marks):
    keys = random.sample(range(5, 60), 7); root = None
    for k in keys: root = _ins(root, k)
    if random.random() < .5:
        return dict(type="nat", question=f"The keys {', '.join(map(str, keys))} are inserted in this order into an initially empty binary search tree. The tree is shown in the figure after all insertions. The height of the tree (number of edges on the longest root-to-leaf path) is ______.",
                    figure={"kind": "tree", "root": _tree(root)}, answer=_nat(_height(root)), explanation="Longest root-to-leaf path in the tree drawn.")
    good = " ".join(map(str, _walk(root, "post"))); bad = [" ".join(map(str, x)) for x in (_walk(root, "pre"), _walk(root, "in"), _walk(root, "post")[::-1])]
    sw = _walk(root, "post")[:]; sw[0], sw[1] = sw[1], sw[0]; bad.append(" ".join(map(str, sw)))
    o, a = _mcq(good, bad)
    return dict(type="mcq", question=f"The keys {', '.join(map(str, keys))} are inserted in this order into an initially empty BST (no rebalancing). The post-order traversal of the resulting tree is", options=o, answer=a,
                figure={"kind": "tree", "root": _tree(root)}, explanation=f"Post-order = left, right, root → {good}.")
def pds_heap(marks):
    arr = random.sample(range(1, 60), 7)
    def heapify(a):
        a = a[:]; n = len(a)
        for i in range(n // 2 - 1, -1, -1):
            j = i
            while True:
                l, r, m = 2 * j + 1, 2 * j + 2, j
                if l < n and a[l] > a[m]: m = l
                if r < n and a[r] > a[m]: m = r
                if m == j: break
                a[j], a[m] = a[m], a[j]; j = m
        return a
    h = heapify(arr); i = random.randint(0, 2)
    return dict(type="nat", question=f"The array [{', '.join(map(str, arr))}] (0-indexed) is converted into a max-heap using the standard bottom-up BUILD-MAX-HEAP procedure. The element stored at index {i} of the resulting array is ______.",
                answer=_nat(h[i]), explanation=f"Resulting heap array: {h}.")
def pds_c_recursion(marks):
    c0, d, n, m = random.randint(1, 3), random.randint(1, 4), random.randint(5, 9), random.randint(2, 4)
    @lru_cache(None)
    def f(k): return c0 if k <= 1 else f(k - 1) + f(k - 2) + d
    code = f"int f(int n) {{\n    if (n <= 1) return {c0};\n    return f(n - 1) + f(n - 2) + {d};\n}}\nint main() {{\n    printf(\"%d\", f({n}));\n    return 0;\n}}"
    if marks == 1 and random.random() < .5:
        s = sum(i * m for i in range(n + 5) if i % 3 == 1)
        code = f"int main() {{\n    int i, s = 0;\n    for (i = 0; i < {n + 5}; i++)\n        if (i % 3 == 1) s += i * {m};\n    printf(\"%d\", s);\n    return 0;\n}}"
        return dict(type="nat", question="The output of the following C program is ______.", code=code, answer=_nat(s), explanation="Sum of i·%d for i ≡ 1 (mod 3), i < %d." % (m, n + 5))
    return dict(type="nat", question="What is the output of the following C program?", code=code, answer=_nat(f(n)), explanation=f"f satisfies f(k)=f(k-1)+f(k-2)+{d}, f(0)=f(1)={c0} → f({n}) = {f(n)}.")

# ── OPERATING SYSTEM ─────────────────────────────────────────────────────────
def os_paging(marks):
    fr, alg = random.choice([3, 4]), random.choice(["FIFO", "LRU"])
    ref = [random.randint(1, 6) for _ in range(14)]; mem, faults = [], 0
    for r in ref:
        if r in mem:
            if alg == "LRU": mem.remove(r); mem.append(r)
            continue
        faults += 1
        if len(mem) == fr: mem.pop(0)
        mem.append(r)
    return dict(type="nat", question=f"A system uses demand paging with {fr} page frames, all initially empty, and the {alg} page replacement policy. The page reference string is given in the table. The number of page faults is ______.",
                context="Position | " + " | ".join(str(i + 1) for i in range(len(ref))) + "\nPage | " + " | ".join(map(str, ref)), answer=_nat(faults), explanation=f"Simulating {alg} with {fr} frames gives {faults} faults.")
def os_sched(marks):
    n = 4; at = sorted(random.sample(range(0, 7), n)); bt = [random.randint(2, 8) for _ in range(n)]; pol = random.choice(["SJF", "FCFS", "RR"]); tq = random.choice([2, 3])
    procs = [{"n": f"P{i+1}", "a": at[i], "b": bt[i], "rem": bt[i]} for i in range(n)]; t, done, seg = 0, {}, []
    if pol == "RR":
        q, seen = [], set()
        def arrive():
            for p in procs:
                if p["a"] <= t and p["n"] not in seen: seen.add(p["n"]); q.append(p)
        arrive()
        while len(done) < n:
            if not q: t = min(p["a"] for p in procs if p["n"] not in seen); arrive(); continue
            p = q.pop(0); run = min(tq, p["rem"]); seg.append([p["n"], t, t + run]); t += run; p["rem"] -= run; arrive()
            if p["rem"] > 0: q.append(p)
            else: done[p["n"]] = t
    else:
        rem = procs[:]
        while rem:
            ready = [p for p in rem if p["a"] <= t] or [min(rem, key=lambda p: p["a"])]
            p = min(ready, key=(lambda p: (p["b"], p["a"])) if pol == "SJF" else (lambda p: (p["a"], p["n"])))
            t = max(t, p["a"]); seg.append([p["n"], t, t + p["b"]]); t += p["b"]; done[p["n"]] = t; rem.remove(p)
    wt = sum(done[p["n"]] - p["a"] - p["b"] for p in procs) / n
    desc = {"SJF": "non-preemptive Shortest Job First (ties broken by earlier arrival)", "FCFS": "First-Come-First-Served", "RR": f"Round Robin with time quantum {tq} (a newly arriving process is queued before the pre-empted one)"}[pol]
    return dict(type="nat", question=f"Four processes arrive as shown and are scheduled using {desc}. The average waiting time (rounded to 2 decimals) is ______.",
                context="Process | Arrival | Burst\n" + "\n".join(f"{p['n']} | {p['a']} | {p['b']}" for p in procs), answer=_nat(wt, 0.01),
                figure={"kind": "gantt", "segments": seg, "caption": "Gantt chart of the schedule (shown after the exam in the explanation)", "hidden": True}, explanation=f"Gantt: {seg}. Average waiting time = {wt:.2f}.")

# ── COMPUTER ORGANIZATION ────────────────────────────────────────────────────
def coa_cache(marks):
    a, cs, bs, ways = random.choice([32, 36, 40]), random.choice([16, 32, 64, 128]), random.choice([16, 32, 64]), random.choice([1, 2, 4, 8])
    sets = cs * 1024 // (bs * ways); tag = a - int(math.log2(sets)) - int(math.log2(bs))
    kind = "direct-mapped" if ways == 1 else f"{ways}-way set-associative"
    return dict(type="nat", question=f"A {kind} cache of size {cs} KB has a block size of {bs} bytes. The physical address is {a} bits wide and memory is byte-addressable. The number of tag bits per cache line is ______.",
                answer=_nat(tag), explanation=f"sets = {sets}, index = {int(math.log2(sets))} bits, offset = {int(math.log2(bs))} bits, tag = {a} − index − offset = {tag}.")
def coa_amat(marks):
    h1, t1, t2, tm = random.choice([.9, .95, .8]), random.choice([1, 2]), random.choice([8, 10, 12]), random.choice([100, 120, 150]); h2 = random.choice([.7, .8, .9])
    v = t1 + (1 - h1) * (t2 + (1 - h2) * tm)
    return dict(type="nat", question=f"A processor has a two-level cache hierarchy. L1 hit ratio {h1}, access time {t1} ns; L2 (accessed on an L1 miss) local hit ratio {h2}, access time {t2} ns; main memory access time {tm} ns. Assume the access times are sequential (L2 is accessed only after L1 misses). The average memory access time in ns (2 decimals) is ______.",
                answer=_nat(v, 0.01), explanation=f"AMAT = {t1} + {1-h1:.2f}·({t2} + {1-h2:.2f}·{tm}) = {v:.2f} ns.")
def coa_pipeline(marks):
    k, n, t = random.choice([4, 5, 6]), random.choice([100, 200, 500, 1000]), random.choice([1, 2, 4])
    stalls = random.choice([0, 10, 20, 40]); cyc = k + n - 1 + stalls
    return dict(type="nat", question=f"A {k}-stage instruction pipeline has a clock cycle of {t} ns. A program of {n} instructions is executed; once the pipeline is full one instruction completes per cycle, and hazards insert {stalls} stall cycles in total. The total execution time in ns is ______.",
                answer=_nat(cyc * t), explanation=f"cycles = {k} + {n} − 1 + {stalls} = {cyc}; time = {cyc}·{t} = {cyc*t} ns.")

# ── COMPUTER NETWORKS ────────────────────────────────────────────────────────
def cn_frag(marks):
    mtu, size, hdr = random.choice([(576, 1500, 20), (1000, 3020, 20), (500, 2000, 20), (1200, 4020, 20)])
    pay = mtu - hdr; pay -= pay % 8; total = size - hdr; nfr = math.ceil(total / pay)
    off = (nfr - 1) * pay // 8
    ask = random.choice(["count", "offset"])
    return dict(type="nat", question=f"An IP datagram of total size {size} bytes (including a {hdr}-byte header, no options) is sent over a link with MTU {mtu} bytes. " +
                ("The number of fragments produced is ______." if ask == "count" else "The value of the fragment-offset field of the last fragment is ______."),
                answer=_nat(nfr if ask == "count" else off), explanation=f"Max payload per fragment = {pay} bytes; data = {total} bytes → {nfr} fragments; last offset = {(nfr-1)*pay}/8 = {off}.")
def cn_stopwait(marks):
    bw, d, fr = random.choice([1, 2, 10]), random.choice([5, 10, 20, 25]), random.choice([1000, 2000, 4000, 8000])
    tt = fr / (bw * 1e6) * 1000; rtt = 2 * d; u = tt / (tt + rtt) * 100
    return dict(type="nat", question=f"A stop-and-wait protocol runs over a {bw} Mbps link with one-way propagation delay {d} ms. Frames are {fr} bits; acknowledgements are negligibly small. The link utilisation in percent (2 decimals) is ______.",
                answer=_nat(u, 0.02), explanation=f"T_t = {tt:.3f} ms, RTT = {rtt} ms, U = T_t/(T_t+RTT) = {u:.2f}%.")
def cn_subnet(marks):
    p = random.choice([20, 22, 24, 26]); hosts = 2 ** (32 - p) - 2
    return dict(type="nat", question=f"An organisation is allocated the CIDR block 192.168.0.0/{p}. The maximum number of usable host addresses (excluding network and broadcast) is ______.", answer=_nat(hosts), explanation=f"2^(32−{p}) − 2 = {hosts}.")

# ── THEORY OF COMPUTATION / DIGITAL / DB / MATH ─────────────────────────────
def toc_mod_dfa(marks):
    a, b = random.choice([2, 3, 4]), random.choice([2, 3, 5])
    return dict(type="nat", question=f"Let L be the set of strings over {{0, 1}} in which the number of 0s is divisible by {a} and the number of 1s is divisible by {b}. The number of states in the minimal DFA accepting L is ______.", answer=_nat(a * b), explanation=f"Product construction of two mod counters, all {a}×{b} states distinguishable → {a*b}.")
def toc_binary_div(marks):
    k = random.choice([3, 5, 7, 9, 11])
    return dict(type="nat", question=f"The minimal DFA accepting the set of binary strings (read most-significant bit first, including the empty string) whose value is divisible by {k} has ______ states.", answer=_nat(k), explanation=f"State = value mod {k}; all {k} residues are reachable and pairwise distinguishable.")
def dl_mux(marks):
    m, k = random.choice([(2, 6), (4, 3), (4, 4), (8, 2)]); n = m ** k
    return dict(type="nat", question=f"The minimum number of {m}-to-1 multiplexers needed to construct a single {n}-to-1 multiplexer is ______.", answer=_nat((n - 1) // (m - 1)), explanation=f"Tree with fan-in {m}: ({n} − 1)/({m} − 1) = {(n-1)//(m-1)}.")
def dl_twos(marks):
    b = random.choice([6, 7, 8, 10, 12]); lo = -2 ** (b - 1); hi = 2 ** (b - 1) - 1; ask = random.choice(["min", "max"])
    return dict(type="nat", question=f"In two's complement representation with {b} bits, the {'smallest' if ask=='min' else 'largest'} representable integer is ______.", answer=_nat(lo if ask == "min" else hi), explanation=f"Range is [−2^{b-1}, 2^{b-1}−1] = [{lo}, {hi}].")
def db_blocks(marks):
    rec, blk, n = random.choice([60, 75, 100, 120]), random.choice([1024, 2048, 4096]), random.choice([10000, 25000, 50000, 100000])
    per = blk // rec; nb = math.ceil(n / per)
    return dict(type="nat", question=f"A file has {n} fixed-length unspanned records of {rec} bytes each, stored in disk blocks of {blk} bytes. The number of blocks needed is ______.", answer=_nat(nb), explanation=f"Records/block = ⌊{blk}/{rec}⌋ = {per}; blocks = ⌈{n}/{per}⌉ = {nb}.")
def db_btree(marks):
    p = random.choice([3, 4, 5, 6]); h = random.choice([2, 3])
    keys = (p ** h) - 1
    return dict(type="nat", question=f"A B-tree of order {p} (each node has at most {p} children, hence at most {p-1} keys) has {h} levels (root at level 1, all leaves at level {h}). The maximum number of keys it can store is ______.", answer=_nat(keys), explanation=f"Full tree: ({p}^{h} − 1) keys.")
def math_prob(marks):
    n, k, p = random.choice([(5, 2, .5), (6, 3, .5), (4, 1, .5), (5, 3, .5), (8, 4, .5)])
    v = math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    return dict(type="nat", question=f"A fair coin is tossed {n} times. The probability of getting exactly {k} heads (rounded to 3 decimals) is ______.", answer=_nat(v, .0006), explanation=f"C({n},{k})/2^{n} = {v:.4f}.")
def math_det(marks):
    while True:
        M = [[random.randint(-3, 4) for _ in range(3)] for _ in range(3)]
        d = round(M[0][0]*(M[1][1]*M[2][2]-M[1][2]*M[2][1]) - M[0][1]*(M[1][0]*M[2][2]-M[1][2]*M[2][0]) + M[0][2]*(M[1][0]*M[2][1]-M[1][1]*M[2][0]))
        if d != 0: break
    ask = random.choice(["det", "eig"])
    return dict(type="nat", question=("The determinant of the matrix in the table is ______." if ask == "det" else "The product of all eigenvalues of the matrix in the table is ______."),
                context="\n".join(" | ".join(map(str, r)) for r in M), answer=_nat(d), explanation=f"det = {d}" + ("; product of eigenvalues = determinant." if ask == 'eig' else "."))
def math_sets(marks):
    a, b = random.randint(3, 6), random.randint(2, 5)
    return dict(type="nat", question=f"Let A be a set with {a} elements and B a set with {b} elements. The number of relations from A to B that are functions from A to B is ______.", answer=_nat(b ** a), explanation=f"{b}^{a} = {b**a}.")

# ── GENERAL APTITUDE ─────────────────────────────────────────────────────────
def ga_chart(marks):
    yrs = [2019 + i for i in range(5)]; vals = [random.randint(20, 90) for _ in yrs]; i, j = sorted(random.sample(range(5), 2))
    pct = (vals[j] - vals[i]) / vals[i] * 100
    ask = random.choice(["pct", "avg"])
    if ask == "pct":
        v = round(pct, 1); q = f"The bar chart shows the annual sales (in thousands of units) of a company. The percentage change in sales from {yrs[i]} to {yrs[j]} (rounded to one decimal place; negative for a decrease) is"
        o, a = _mcq(f"{v}%", [f"{round(-v,1)}%", f"{round(pct*vals[i]/vals[j],1)}%", f"{round(v+5,1)}%", f"{round(v-7.5,1)}%", f"{round(abs(v)/2,1)}%"])
        ex = f"({vals[j]} − {vals[i]})/{vals[i]} × 100 = {v}%."
    else:
        v = round(sum(vals) / 5, 1); q = "The bar chart shows the annual sales (in thousands of units) of a company. The average annual sales over the five years (in thousands) is"
        o, a = _mcq(_fmt(v), [_fmt(v + 2.5), _fmt(v - 3.2), _fmt(round(sum(vals[:4]) / 4, 1)), _fmt(round(sum(vals[1:]) / 4, 1)), _fmt(v + 6)]); ex = f"Sum = {sum(vals)}; mean = {v}."
    return dict(type="mcq", question=q, options=o, answer=a, figure={"kind": "bar", "labels": [str(y) for y in yrs], "values": vals, "ylabel": "Sales (thousands)"}, explanation=ex)
def ga_work(marks):
    a, b = random.choice([(12, 6), (10, 15), (20, 30), (8, 24), (9, 18)]); t = a * b / (a + b)
    o, c = _mcq(_fmt(round(t, 2)), [_fmt(round((a + b) / 2, 2)), _fmt(round(a * b / (a + b) + 1, 2)), _fmt(abs(a - b)), _fmt(round(t * 2, 2))])
    return dict(type="mcq", question=f"A can complete a job in {a} days and B can complete the same job in {b} days. Working together, they will complete the job in ___ days.", options=o, answer=c, explanation=f"1/{a} + 1/{b} = 1/t → t = {round(t,2)}.")
def ga_ratio(marks):
    x, y, tot = random.choice([(3, 5, 240), (2, 7, 450), (4, 5, 360), (5, 3, 400)]); v = tot * x // (x + y)
    o, c = _mcq(str(v), [str(tot * y // (x + y)), str(tot // 2), str(v + 20), str(v - 15)])
    return dict(type="mcq", question=f"Two numbers are in the ratio {x}:{y} and their sum is {tot}. The number corresponding to the {x} parts is", options=o, answer=c, explanation=f"{tot}×{x}/({x}+{y}) = {v}.")

FAMILIES = {
    "algo": [algo_dijkstra, algo_mst, algo_hash, algo_recurrence], "pds": [pds_bst, pds_heap, pds_c_recursion], "os": [os_paging, os_sched],
    "coa": [coa_cache, coa_amat, coa_pipeline], "cn": [cn_frag, cn_stopwait, cn_subnet], "toc": [toc_mod_dfa, toc_binary_div], "dl": [dl_mux, dl_twos],
    "db": [db_blocks, db_btree], "math": [math_prob, math_det, math_sets], "ga": [ga_chart, ga_work, ga_ratio], "cd": [],
}
def make(subject, marks, exclude=()):
    fs = [f for f in FAMILIES.get(subject, []) if f.__name__ not in exclude] or FAMILIES.get(subject, [])
    if not fs: return None
    f = random.choice(fs); q = f(marks)
    q.setdefault("context", ""); q.setdefault("code", ""); q.setdefault("figure", None); q.setdefault("options", {})
    q.update(subject=subject, marks=marks, src="code", fam=f.__name__)
    return q