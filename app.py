from flask import Flask, render_template, request
import networkx as nx
import time, re, requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import tldextract
from flask import flash

app = Flask(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Demo-Recherche-Web (PageRank + HITS); +https://www.usherbrooke.ca)"}
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_REQUESTS = .1
MAX_SEEDS = 15
MAX_PAGES = 30
MAX_OUTLINKS_PER_PAGE = 10
CRAWL_DEPTH = 3
K = 10


def is_probable_html(resp: requests.Response) -> bool:
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
            return resp.text
        return None
    except requests.RequestException:
        return None


def crawl_and_build_graph(seed_urls, max_pages=MAX_PAGES, max_depth=CRAWL_DEPTH):
    G = nx.DiGraph()
    visited = set()
    frontier = [(u, 0) for u in seed_urls[:MAX_SEEDS]]

    while frontier and len(visited) < max_pages:
        url, depth = frontier.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        html = fetch(url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        if html is None:
            continue

        outlinks = extract_links(url, html)[:MAX_OUTLINKS_PER_PAGE]
        G.add_node(url, domain=domain(url))
        for l in outlinks:
            G.add_node(l, domain=domain(l))
            G.add_edge(url, l)
            if l not in visited:
                frontier.append((l, depth + 1))
    return G


def compute_pagerank(G: nx.DiGraph, damping: float = 0.85):
    return nx.pagerank(G, alpha=damping)


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
        if critere == "PageRank":
            G = crawl_and_build_graph(seeds)
            pr = compute_pagerank(G)
            scores["PageRank"] = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:K]
        elif critere == "HITS-autorite":
            scores["HITS-autorite"] = "À implémenter"
        results = {"query": query, "scores": scores}

    return render_template("index.html", results=results)


if __name__ == "__main__":
    app.run(debug=True)
