from flask import Flask, render_template, request
import networkx as nx
import time, re, requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import tldextract
from flask import flash
from time import perf_counter

app = Flask(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Demo-Recherche-Web (PageRank + HITS); +https://www.usherbrooke.ca)"}
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_REQUESTS = .1
MAX_SEEDS = 15
MAX_PAGES = 50
MAX_OUTLINKS_PER_PAGE = 15
CRAWL_DEPTH = 3
K = 10


def is_probable_html(resp: requests.Response)  -> bool:
    return "text/html" in resp.headers.get("Content-Type", "")


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    normalized = parsed._replace(fragment="", query=parsed.query)
    return normalized.geturl()


def looks_like_webpage(url: str) -> bool:
    return not re.search(r"\.(pdf|png|jpg|jpeg|gif|svg|zip|rar|tar|mp4|mp3)(\?|$)", url, re.I)


def extract_links(base_url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        if looks_like_webpage(absolute):
            links.add(normalize_url(absolute))
    return list(links)


def domain(url: str) -> str:
    ext = tldextract.extract(url)
    return ".".join([part for part in [ext.domain, ext.suffix] if part])


def fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200 and is_probable_html(resp):
            return resp.url,resp.text
        return None
    except requests.RequestException:
        return None


def crawl_and_build_graph(query, seed_urls, max_pages=MAX_PAGES, max_depth=CRAWL_DEPTH):
    G = nx.DiGraph()
    visited = set()
    frontier = [(u, 0) for u in seed_urls[:MAX_SEEDS]]
    query_terms = [t.lower() for t in query.split() if t.strip()]

    def is_relevant(html: str) -> bool:
        soup = BeautifulSoup(html, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.decompose()
        
        text = soup.get_text(separator=' ', strip=True).lower()
        
        return any(term in text for term in query_terms) if query_terms else True

    pages_added = 0
    pages_rejected = 0

    while frontier and len(visited) < max_pages:
        url, depth = frontier.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        fetch_result = fetch(url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        
        if fetch_result is None:
            continue
        
        final_url, html_content = fetch_result
        final_url_normalized = normalize_url(final_url)

        # Vérifier la pertinence SEULEMENT si depth > 0 (pas pour les seeds)
        if depth > 0 and not is_relevant(html_content):
            pages_rejected += 1
            continue

        # La page est pertinente OU c'est un seed (depth=0)
        pages_added += 1
        url_to_add = final_url_normalized

        G.add_node(url_to_add, domain=domain(url_to_add), html=html_content)

        # Extraire les liens directement sans filtrage
        all_outlinks = extract_links(url, html_content)
        outlinks = all_outlinks[:MAX_OUTLINKS_PER_PAGE]

        print(f"[{pages_added}/{max_pages}] Depth={depth} | {len(all_outlinks)} liens trouvés, {len(outlinks)} gardés | {url[:70]}")
        
        for l in outlinks:
            G.add_node(l, domain=domain(l))
            G.add_edge(url_to_add, l)
            if l not in visited:
                frontier.append((l, depth + 1))
    
    return G
  

def compute_pagerank(G: nx.DiGraph, damping: float = 0.85):
    return nx.pagerank(G, alpha=damping)

def compute_hits(G: nx.DiGraph):
    return nx.hits(G)


@app.route("/", methods=["GET", "POST"])
def index():
    results = None
    if request.method == "POST":
        seeds_raw = request.form.get("seeds", "").strip()
        query = request.form.get("query", "").strip()
        critere = request.form.get("critere", "PageRank")

        if not seeds_raw or not query:
            flash("Veuillez renseigner au moins un seed et une requête.", "danger")
            return render_template("index.html")

        seeds = [s.strip() for s in seeds_raw.splitlines() if s.strip()]
        query = request.form.get("query", "")
        scores = {}

        crawl_t0 = perf_counter()
        G = crawl_and_build_graph(query, seeds)
        crawl_time = perf_counter() - crawl_t0

        rank_time = 0.0

        if critere == "PageRank":
            t0 = perf_counter()
            pr = compute_pagerank(G)
            rank_time = perf_counter() - t0
            scores["PageRank"] = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:K]

        elif critere == "HITS-autorite":
            t0 = perf_counter()
            authorities, hubs = compute_hits(G)
            rank_time = perf_counter() - t0 
            scores["HITS-autorite"] = sorted(authorities.items(), key=lambda x: x[1], reverse=True)[:K]
            
        results = {"query": query, "scores": scores, "crawl_time": crawl_time, "rank_time": rank_time}

    return render_template("index.html", results=results)


if __name__ == "__main__":
    app.run(debug=True)
