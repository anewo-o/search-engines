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
MAX_PAGES = 50
MAX_OUTLINKS_PER_PAGE = 10
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


def crawl_and_build_graph(seed_urls, max_pages=MAX_PAGES, max_depth=CRAWL_DEPTH):
    G = nx.DiGraph()
    visited = set()
    frontier = [(u, 0) for u in seed_urls[:MAX_SEEDS]]

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

        url_to_add = final_url_normalized

        G.add_node(url_to_add, domain=domain(url_to_add), html=html_content)

        outlinks = extract_links(url, html_content)[:MAX_OUTLINKS_PER_PAGE]
        for l in outlinks:
            G.add_node(l, domain=domain(l))
            G.add_edge(url_to_add, l)
            if l not in visited:
                frontier.append((l, depth + 1))
    return G


def filter_graph_by_query(G: nx.DiGraph, query: str) -> nx.DiGraph:
    """
    Crée un sous-graphe (G_prime) contenant uniquement les nœuds dont le contenu
    HTML contient les mots-clés de la requête (query).
    
    Args:
        G (nx.DiGraph): Le graphe complet construit par le crawler.
        query (str): La requête de recherche de l'utilisateur.
        
    Returns:
        nx.DiGraph: Le sous-graphe contenant uniquement les nœuds pertinents.
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return G
    
    # Séparer les mots de la requête
    query_terms = query_lower.split()  
    
    relevant_nodes = set()
    
    for node_url in G.nodes:
        if 'html' in G.nodes[node_url] and G.nodes[node_url]['html'] is not None:
            html_content = G.nodes[node_url]['html'].lower()
            
            # Vérifie si TOUS les mots sont présents (peu importe l'ordre ou la distance)
            if all(term in html_content for term in query_terms):
                relevant_nodes.add(node_url)

    G_prime = G.subgraph(relevant_nodes).copy()
    
    if not G_prime.nodes:
         return nx.DiGraph()
         
    return G_prime


def compute_pagerank(G: nx.DiGraph, damping: float = 0.85):
    return nx.pagerank(G, alpha=damping)

def compute_hits(G: nx.DiGraph):
    """
    Calcule les scores de Hub et d'Autorité pour chaque nœud du graphe G.
    """
    # La fonction hits de NetworkX retourne deux dictionnaires : hubs et authorities.
    hubs, authorities = nx.hits(G)
    return authorities, hubs # Retourne (Autorité, Hub)


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
        G = crawl_and_build_graph(seeds)
        if critere == "PageRank":
            G_prime = filter_graph_by_query(G, query)

            if not G_prime.nodes:
                error_message = f"Aucun résultat trouvé pour la requête : '{query}' dans les pages explorées."
                return render_template("index.html",error_message)
            
            pr = compute_pagerank(G_prime)
            scores["PageRank"] = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:K]
        else: # HITS-autorite ou HITS-hub
            # Étape cruciale : Filtrage du graphe basé sur la requête
            # Ceci crée G_prime, le sous-graphe thématique
            G_prime = filter_graph_by_query(G, query)
            
            if not G_prime.nodes:
                error_message = f"Aucun résultat trouvé pour la requête : '{query}' dans les pages explorées."
                return render_template("index.html",error_message)
                
            # Les calculs HITS sont maintenant effectués sur le sous-graphe G_prime
            authorities, hubs = compute_hits(G) 

            if critere == "HITS-autorite":
                scores["HITS-autorite"] = sorted(authorities.items(), key=lambda x: x[1], reverse=True)[:K]
                
            elif critere == "HITS-hub":
                scores["HITS-hub"] = sorted(hubs.items(), key=lambda x: x[1], reverse=True)[:K]
        
        results = {"query": query, "scores": scores}

    return render_template("index.html", results=results)


if __name__ == "__main__":
    app.run(debug=True)
