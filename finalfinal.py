"""
app_python_explorer_v2.py — Python Code Intelligence
══════════════════════════════════════════════════════
3 vues : Graphe d'exécution + Diagrammes UML cross-module + Features Louvain
UML : détecte héritage, associations et appels entre classes de fichiers différents.
GRAPHE ENRICHI : imports réels entre modules (imports_module, imports_object)

Dépendances : pip install streamlit networkx pyvis
"""

import ast
import base64
import html as html_lib
import json
import re
import tempfile
import textwrap
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx
import streamlit as st
import streamlit.components.v1 as components

# ══════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Python Code Intelligence",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════
# STYLES
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@500;700&family=DM+Sans:wght@400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background: #0e1117; color: #e0e0e0;
}
h1 { font-family:'Syne',sans-serif; font-weight:700;
     background:linear-gradient(90deg,#58a6ff,#a5d6ff);
     -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
h2, h3 { font-family:'Syne',sans-serif; font-weight:500; color:#c9d1d9; }

.stButton>button {
    background:linear-gradient(135deg,#1f6feb,#388bfd);
    color:#fff; border:none; border-radius:8px;
    padding:.55em 1.5em; font-family:'DM Sans',sans-serif;
    font-size:.9rem; cursor:pointer; transition:opacity .2s, transform .1s;
}
.stButton>button:hover  { opacity:.88; }
.stButton>button:active { transform:scale(.98); }

div[data-testid="stTabs"] > div > div > button {
    font-family:'Syne',sans-serif !important;
    font-size:1rem !important; font-weight:500 !important;
}

.kpi-row { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:1rem; }
.kpi {
    background:#161b22; border:1px solid #30363d;
    border-radius:10px; padding:.75rem 1rem;
    text-align:center; min-width:90px;
}
.kpi .v { font-size:1.7rem; font-weight:700;
           font-family:'Syne',sans-serif; color:#58a6ff; }
.kpi .l { font-size:.68rem; color:#8b949e; margin-top:2px; }

.badge { display:inline-block; padding:2px 8px; border-radius:20px;
         font-size:.72rem; font-weight:600; margin:1px;
         font-family:'JetBrains Mono',monospace; }
.bf  { background:#1f4068; color:#58a6ff; }
.bc  { background:#3b2f0e; color:#e3b341; }
.ba  { background:#1b2d1b; color:#3fb950; }
.bi  { background:#2d1b2d; color:#d2a8ff; }
.bx  { background:#1e2828; color:#56d364; }

.section-hdr {
    font-family:'Syne',sans-serif; font-size:1rem; font-weight:600;
    color:#58a6ff; border-bottom:1px solid #30363d;
    padding-bottom:5px; margin:1rem 0 .7rem;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ══════════════════════════════════════════════════════════
@dataclass
class FunctionInfo:
    name: str;
    lineno: int;
    end_lineno: int
    args: list[str];
    docstring: Optional[str]
    calls: list[str];
    is_async: bool
    node: ast.FunctionDef


@dataclass
class ClassInfo:
    name: str;
    lineno: int;
    end_lineno: int
    bases: list[str];
    decorators: list[str];
    docstring: Optional[str]
    methods: list[FunctionInfo] = field(default_factory=list)
    node: ast.ClassDef = None


@dataclass
class ImportInfo:
    """Information détaillée sur un import"""
    module: str
    name: str
    alias: Optional[str] = None


@dataclass
class ModuleInfo:
    filepath: str;
    module_name: str;
    docstring: Optional[str]
    imports: list[str]
    import_details: list[ImportInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    source_lines: list[str] = field(default_factory=list)


@dataclass
class CrossRelation:
    """Une relation entre deux classes de modules différents."""
    kind: str
    src_module: str
    src_class: str
    dst_module: str
    dst_class: str
    label: str


# Palette de couleurs pour les features
FEATURE_COLORS = [
    ("#1f4068", "#58a6ff"),  # bleu
    ("#3b2f0e", "#e3b341"),  # ambre
    ("#0d2818", "#56d364"),  # vert
    ("#2d1020", "#f778ba"),  # rose
    ("#1e1e2e", "#c678dd"),  # violet
    ("#1a2a2a", "#4ec9b0"),  # teal
    ("#2a1a1a", "#f97583"),  # coral
    ("#1a1a30", "#79c0ff"),  # bleu clair
    ("#2a2a1a", "#e2c08d"),  # sable
    ("#1a2a1a", "#85e89d"),  # vert clair
]


@dataclass
class Feature:
    """Une fonctionnalité détectée dans le projet."""
    name: str
    label: str
    origin: str
    modules: list[str]
    classes: list[tuple[str, str]]
    functions: list[tuple[str, str]]
    description: str
    color_bg: str = "#1f4068"
    color_fg: str = "#58a6ff"

    @property
    def total_symbols(self) -> int:
        return len(self.modules) + len(self.classes) + len(self.functions)


# ══════════════════════════════════════════════════════════
# PARSER
# ══════════════════════════════════════════════════════════
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".tox", "dist",
    "build", ".mypy_cache", ".pytest_cache", "node_modules", ".eggs",
}


def collect_py_files(project_path: str) -> list[Path]:
    root = Path(project_path).resolve()
    if not root.exists():  raise FileNotFoundError(f"Introuvable : {root}")
    if not root.is_dir():  raise NotADirectoryError(f"Pas un dossier : {root}")
    return sorted(p for p in root.rglob("*.py")
                  if not any(ex in p.parts for ex in EXCLUDE_DIRS))


def read_file(fp: Path):
    try:
        return fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_source(src: str, fname: str = "<unknown>"):
    try:
        return ast.parse(src, filename=fname)
    except SyntaxError:
        return None


def extract_imports_detailed(tree: ast.Module) -> list[ImportInfo]:
    """Extrait les imports avec détails : module, nom, alias"""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for alias in n.names:
                out.append(ImportInfo(module=alias.name, name=alias.name, alias=alias.asname))
        elif isinstance(n, ast.ImportFrom):
            module = n.module or ""
            for alias in n.names:
                out.append(ImportInfo(module=module, name=alias.name, alias=alias.asname))
    return out


def extract_imports(tree: ast.Module) -> list[str]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names: out.append(a.name)
        elif isinstance(n, ast.ImportFrom):
            m = n.module or ""
            for a in n.names: out.append(f"{m}.{a.name}")
    return out


def _resolve_name(node) -> Optional[str]:
    if isinstance(node, ast.Name):      return node.id
    if isinstance(node, ast.Attribute): return f"{_resolve_name(node.value)}.{node.attr}"
    return None


def _get_calls(fn) -> list[str]:
    calls = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            nm = _resolve_name(n.func)
            if nm and nm not in calls: calls.append(nm)
    return calls


def _build_func(node) -> FunctionInfo:
    return FunctionInfo(
        name=node.name, lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", node.lineno),
        args=[a.arg for a in node.args.args],
        docstring=ast.get_docstring(node),
        calls=_get_calls(node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        node=node,
    )


def extract_functions(tree: ast.Module) -> list[FunctionInfo]:
    return [_build_func(n) for n in ast.iter_child_nodes(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def extract_classes(tree: ast.Module) -> list[ClassInfo]:
    out = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef): continue
        out.append(ClassInfo(
            name=node.name, lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            bases=[_resolve_name(b) or ast.unparse(b) for b in node.bases],
            decorators=[_resolve_name(d) or ast.unparse(d) for d in node.decorator_list],
            docstring=ast.get_docstring(node),
            methods=[_build_func(c) for c in ast.iter_child_nodes(node)
                     if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))],
            node=node,
        ))
    return out


def extract_attributes(class_node: ast.ClassDef) -> list[tuple[str, str]]:
    attrs, seen = [], set()
    for node in ast.iter_child_nodes(class_node):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.AnnAssign):
                    if (isinstance(stmt.target, ast.Attribute) and
                            isinstance(stmt.target.value, ast.Name) and
                            stmt.target.value.id == "self"):
                        nm = stmt.target.attr
                        if nm not in seen:
                            try:
                                tp = ast.unparse(stmt.annotation)
                            except Exception:
                                tp = "Any"
                            attrs.append((nm, tp));
                            seen.add(nm)
                elif isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if (isinstance(t, ast.Attribute) and
                                isinstance(t.value, ast.Name) and
                                t.value.id == "self" and t.attr not in seen):
                            attrs.append((t.attr, ""));
                            seen.add(t.attr)
    return attrs


def parse_one_file(fp: Path, root: Path):
    src = read_file(fp)
    if src is None: return None
    tree = parse_source(src, fname=str(fp))
    if tree is None: return None
    rel = fp.relative_to(root)
    return ModuleInfo(
        filepath=str(fp),
        module_name=".".join(rel.with_suffix("").parts),
        docstring=ast.get_docstring(tree),
        imports=extract_imports(tree),
        import_details=extract_imports_detailed(tree),
        functions=extract_functions(tree),
        classes=extract_classes(tree),
        source_lines=src.splitlines(keepends=True),
    )


@st.cache_data(show_spinner=False)
def parse_project(project_path: str) -> list[ModuleInfo]:
    root = Path(project_path).resolve()
    files = collect_py_files(project_path)
    out = []
    for fp in files:
        m = parse_one_file(fp, root)
        if m: out.append(m)
    return out


# ══════════════════════════════════════════════════════════
# CONSTRUCTION DU GRAPHE ENRICHI AVEC IMPORTS RÉELS
# ══════════════════════════════════════════════════════════

def build_feature_graph(modules: list[ModuleInfo]) -> nx.Graph:
    """
    Construit un graphe NON-orienté pondéré pour Louvain.
    ENRICHI avec les imports réels entre modules.

    Nœuds  : module_name de chaque fichier .py
    Arêtes :
        - import direct (3.0) — NOUVEAU : détecté via import_details
        - héritage cross-mod (4.0)
        - association attribut (3.0)
        - appel méthode (2.0)
        - même package (1.0)
    """
    G = nx.Graph()

    for m in modules:
        G.add_node(m.module_name,
                   label=m.module_name.split(".")[-1],
                   nb_classes=len(m.classes),
                   nb_funcs=len(m.functions))

    all_mod_names = {m.module_name for m in modules}

    def add_edge(u, v, w):
        if u == v: return
        if G.has_edge(u, v):
            G[u][v]["weight"] += w
        else:
            G.add_edge(u, v, weight=w)

    # ── 1. IMPORTS RÉELS (NOUVEAU) ────────────────────────
    # Utilise import_details pour détecter les imports précis
    module_exports = defaultdict(set)
    for m in modules:
        for c in m.classes:
            module_exports[m.module_name].add(c.name)
        for f in m.functions:
            module_exports[m.module_name].add(f.name)

    for m in modules:
        for imp in m.import_details:
            # Chercher le module source dans le projet
            for other_mod in modules:
                if other_mod.module_name == imp.module:
                    # Import de module complet : import foo
                    if imp.name == imp.module:
                        add_edge(m.module_name, other_mod.module_name, 3.0)
                    # Import d'objet : from foo import Bar
                    elif imp.name in module_exports[other_mod.module_name]:
                        add_edge(m.module_name, other_mod.module_name, 3.0)
                    break

    # ── 2. Relations cross-module (héritage, associations, appels) ──
    global_cls: dict[str, str] = {}
    for m in modules:
        for c in m.classes: global_cls[c.name] = m.module_name

    for m in modules:
        local_cls = {c.name for c in m.classes}
        for cls in m.classes:
            # Héritage
            for base in cls.bases:
                bs = base.split(".")[-1]
                if bs in global_cls and bs not in local_cls:
                    add_edge(m.module_name, global_cls[bs], 4.0)
            # Associations via attributs
            if cls.node:
                for _, at in extract_attributes(cls.node):
                    for kc, km in global_cls.items():
                        if kc in at and kc not in local_cls:
                            add_edge(m.module_name, km, 3.0)
            # Appels de méthodes
            for mt in cls.methods:
                for call in mt.calls:
                    root = call.split(".")[0]
                    if root in global_cls and root not in local_cls:
                        add_edge(m.module_name, global_cls[root], 2.0)

    # ── 3. Même package ───────────────────────────────────
    for i, ma in enumerate(modules):
        for mb in modules[i + 1:]:
            pa = ma.module_name.split(".")
            pb = mb.module_name.split(".")
            if len(pa) >= 2 and len(pb) >= 2 and pa[0] == pb[0]:
                add_edge(ma.module_name, mb.module_name, 1.0)

    return G


def build_cross_relations(modules: list[ModuleInfo]) -> list[CrossRelation]:
    """Détecte 3 types de relations inter-modules"""
    global_cls: dict[str, str] = {}
    for m in modules:
        for c in m.classes:
            global_cls[c.name] = m.module_name

    relations: list[CrossRelation] = []
    seen: set[tuple] = set()

    def add(kind, sm, sc, dm, dc, label):
        key = (kind, sc, dc)
        if sm != dm and key not in seen:
            seen.add(key)
            relations.append(CrossRelation(kind, sm, sc, dm, dc, label))

    for m in modules:
        local_cls = {c.name for c in m.classes}

        for cls in m.classes:
            for base in cls.bases:
                base_short = base.split(".")[-1]
                if base_short in global_cls and base_short not in local_cls:
                    add("inherits", m.module_name, cls.name,
                        global_cls[base_short], base_short, base_short)

            if cls.node:
                for attr_name, attr_type in extract_attributes(cls.node):
                    for known_cls, known_mod in global_cls.items():
                        if known_cls in attr_type and known_cls not in local_cls:
                            add("associates", m.module_name, cls.name,
                                known_mod, known_cls, attr_name)

            for mt in cls.methods:
                for call in mt.calls:
                    root_name = call.split(".")[0]
                    if root_name in global_cls and root_name not in local_cls:
                        add("uses", m.module_name, cls.name,
                            global_cls[root_name], root_name, f"{mt.name}→{call}")

    return relations


# ══════════════════════════════════════════════════════════
# DÉTECTION DE FEATURES PAR LOUVAIN
# ══════════════════════════════════════════════════════════

def detect_features_louvain(modules: list[ModuleInfo], resolution: float = 1.0) -> list[Feature]:
    """
    Louvain via greedy_modularity_communities de NetworkX.
    Utilise le graphe enrichi avec imports réels.
    """
    G = build_feature_graph(modules)
    if len(G.nodes) == 0: return []

    try:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = list(greedy_modularity_communities(G, weight="weight", resolution=resolution))
    except Exception:
        communities = [list(c) for c in nx.connected_components(G)]

    if not communities: return []

    mod_idx = {m.module_name: m for m in modules}

    STOPWORDS = {
        "main", "utils", "helpers", "base", "common", "core", "init", "test", "tests", "config",
        "settings", "constants", "exceptions", "errors", "types", "models", "views", "controllers",
        "handlers", "services", "api", "app", "run", "setup", "manager", "mixin", "abstract",
        "interface", "factory", "builder", "helper", "client", "server", "data", "info", "result",
        "response", "request", "context", "log", "logger", "exception", "src", "lib", "pkg", "mod",
        "obj", "tmp", "temp", "py", "misc", "shared", "generic",
    }

    def tokens(text: str) -> list[str]:
        text = re.sub(r'[_\-.]', ' ', text)
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)
        return [t.lower() for t in text.split() if len(t) >= 4 and t.lower() not in STOPWORDS]

    features: list[Feature] = []
    for i, community in enumerate(sorted(communities, key=len, reverse=True)):
        community = list(community)
        c_color = FEATURE_COLORS[i % len(FEATURE_COLORS)]
        clses: list[tuple[str, str]] = []
        fns: list[tuple[str, str]] = []
        counter: Counter = Counter()

        for mn in community:
            m = mod_idx.get(mn)
            if not m: continue
            for tok in tokens(mn.split(".")[-1]): counter[tok] += 3
            for cls in m.classes:
                clses.append((mn, cls.name))
                for tok in tokens(cls.name): counter[tok] += 2
            for fn in m.functions:
                fns.append((mn, fn.name))
                for tok in tokens(fn.name): counter[tok] += 1

        if counter:
            top = [tok for tok, _ in counter.most_common(3)]
            name = "_".join(top[:2])
            label = " ".join(t.capitalize() for t in top[:2])
        else:
            name = f"cluster_{i + 1}"
            label = f"Cluster {i + 1}"

        top_cls = [c for _, c in clses[:3]]
        desc = (f"{len(community)} module{'s' if len(community) > 1 else ''}, "
                f"{len(clses)} classe{'s' if len(clses) > 1 else ''}, "
                f"{len(fns)} fonction{'s' if len(fns) > 1 else ''}."
                + (f" Classes : {', '.join(top_cls)}." if top_cls else ""))

        features.append(Feature(
            name=name, label=label, origin="louvain",
            modules=community, classes=clses, functions=fns,
            description=desc, color_bg=c_color[0], color_fg=c_color[1],
        ))

    return sorted(features, key=lambda f: f.total_symbols, reverse=True)


def features_by_module(features: list[Feature]) -> dict[str, list[Feature]]:
    idx: dict[str, list[Feature]] = {}
    for ft in features:
        for mn in ft.modules: idx.setdefault(mn, []).append(ft)
    return idx


# ══════════════════════════════════════════════════════════
# GRAPHE DES FEATURES COLORÉ (PyVis — Louvain)
# ══════════════════════════════════════════════════════════

def build_feature_pyvis_html(modules: list[ModuleInfo], features: list[Feature], height: int = 520) -> str:
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:#f78166'>pip install pyvis</p>"

    G_feat = build_feature_graph(modules)
    mod_to_feat: dict[str, Feature] = {}
    for ft in features:
        for mn in ft.modules: mod_to_feat[mn] = ft

    net = Network(height=f"{height}px", width="100%", directed=False,
                  bgcolor="#0d0f14", font_color="#c9d1d9")
    net.barnes_hut(gravity=-6000, central_gravity=0.4,
                   spring_length=100, spring_strength=0.05, damping=0.9)

    for node_id, data in G_feat.nodes(data=True):
        ft = mod_to_feat.get(node_id)
        color = ft.color_fg if ft else "#444"
        bg = ft.color_bg if ft else "#222"
        label = data.get("label", node_id)
        title = (f"<b>{node_id}</b><br>Feature : {ft.label if ft else '–'}<br>"
                 f"Classes : {data.get('nb_classes', 0)} · Fonctions : {data.get('nb_funcs', 0)}")
        size = min(14 + data.get("nb_classes", 0) * 3 + data.get("nb_funcs", 0), 45)
        net.add_node(node_id, label=label, title=title,
                     color={"background": bg, "border": color,
                            "highlight": {"background": color, "border": color}},
                     size=size, font={"size": 10, "color": "#c9d1d9"},
                     borderWidth=2, borderWidthSelected=3)

    max_w = max((d.get("weight", 1) for _, _, d in G_feat.edges(data=True)), default=1)
    for u, v, data in G_feat.edges(data=True):
        w = data.get("weight", 1)
        ft_u = mod_to_feat.get(u)
        ft_v = mod_to_feat.get(v)
        same = ft_u and ft_v and ft_u.name == ft_v.name
        net.add_edge(u, v,
                     width=max(0.5, w / max_w * 4),
                     color=ft_u.color_fg if same and ft_u else "#2a2a2a",
                     dashes=not same,
                     title=f"poids : {w:.1f}")

    net.set_options(json.dumps({
        "interaction": {"hover": True, "tooltipDelay": 100,
                        "navigationButtons": True, "keyboard": True},
        "physics": {"enabled": True},
        "edges": {"smooth": {"type": "continuous"}},
    }))
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        return Path(f.name).read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════
# VUE FEATURES (Louvain)
# ══════════════════════════════════════════════════════════

def render_features_tab(modules: list[ModuleInfo], cross_rels: list[CrossRelation]):
    mod_idx = {m.module_name: m for m in modules}
    features: list[Feature] = st.session_state.get("features", [])

    # Sidebar
    with st.sidebar:
        st.markdown('<div class="section-hdr">🧩 Louvain</div>', unsafe_allow_html=True)
        resolution = st.slider(
            "Résolution", 0.2, 3.0, 1.0, 0.1, key="louvain_res",
            help="< 1 = moins de clusters · > 1 = plus de clusters")
        graph_h_feat = st.slider("Hauteur graphe (px)", 350, 900, 520, 50, key="feat_graph_h")
        detect_btn = st.button("🔍 Détecter les features",
                               use_container_width=True, key="louvain_detect")

    if detect_btn or not features:
        with st.spinner("Algorithme Louvain en cours…"):
            features = detect_features_louvain(modules, resolution=resolution)
            st.session_state["features"] = features

    if not features:
        st.warning("Aucun cluster détecté. Essayez une résolution plus basse.")
        return

    # Graphe PyVis coloré par cluster
    st.markdown('<div class="section-hdr">🕸️ Graphe des dépendances — clusters Louvain</div>',
                unsafe_allow_html=True)
    st.caption(
        f"Résolution : **{resolution}** · **{len(features)}** clusters · "
        "Arêtes pleines = intra-cluster · Pointillées = inter-cluster")

    legend_html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">'
    for ft in features:
        legend_html += (
            f'<span style="background:{ft.color_bg};color:{ft.color_fg};'
            f'padding:2px 10px;border-radius:20px;font-size:.72rem;'
            f'border:1px solid {ft.color_fg}44">{ft.label}</span>')
    legend_html += '</div>'
    st.markdown(legend_html, unsafe_allow_html=True)

    components.html(
        build_feature_pyvis_html(modules, features, height=graph_h_feat),
        height=graph_h_feat + 20, scrolling=False)

    # KPIs
    st.divider()
    nb_mod_a = len({mn for f in features for mn in f.modules})
    nb_cls_a = sum(len(f.classes) for f in features)
    nb_fn_a = sum(len(f.functions) for f in features)
    G_q = build_feature_graph(modules)
    try:
        from networkx.algorithms.community.quality import modularity
        mod_q = modularity(G_q, [{mn for mn in ft.modules} for ft in features], weight="weight")
        mod_str = f"{mod_q:.3f}"
    except Exception:
        mod_str = "–"

    st.markdown(
        f'<div class="kpi-row">'
        f'<div class="kpi"><div class="v" style="color:#c678dd">{len(features)}</div>'
        f'<div class="l">Clusters</div></div>'
        f'<div class="kpi"><div class="v">{nb_mod_a}/{len(modules)}</div>'
        f'<div class="l">Modules couverts</div></div>'
        f'<div class="kpi"><div class="v">{nb_cls_a}</div><div class="l">Classes</div></div>'
        f'<div class="kpi"><div class="v">{nb_fn_a}</div><div class="l">Fonctions</div></div>'
        f'<div class="kpi"><div class="v" style="color:#3fb950">{mod_str}</div>'
        f'<div class="l">Modularité Q</div></div>'
        f'</div>', unsafe_allow_html=True)

    # Cartes des features
    st.markdown('<div class="section-hdr">🗺️ Carte des features</div>', unsafe_allow_html=True)
    max_sym = max((f.total_symbols for f in features), default=1)
    cols3 = st.columns(3)
    for i, feat in enumerate(features):
        with cols3[i % 3]:
            bar_pct = max(5, int(feat.total_symbols / max_sym * 100))
            mod_pills = " ".join(
                f'<code style="font-size:.67rem;color:{feat.color_fg}99">{mn.split(".")[-1]}</code>'
                for mn in feat.modules[:5])
            cls_pills = " ".join(
                f'<code style="font-size:.67rem;color:{feat.color_fg}cc">{c}</code>'
                for _, c in feat.classes[:4])
            st.markdown(f"""
            <div style="background:{feat.color_bg};border:1px solid {feat.color_fg}44;
                        border-left:3px solid {feat.color_fg};border-radius:10px;
                        padding:1rem;margin-bottom:8px">
              <div style="color:{feat.color_fg};font-family:'Syne',sans-serif;
                          font-weight:600;font-size:.95rem;margin-bottom:5px">{feat.label}</div>
              <div style="background:{feat.color_fg}1a;border-radius:4px;height:3px;margin-bottom:8px">
                <div style="background:{feat.color_fg};width:{bar_pct}%;height:3px;border-radius:4px"></div>
              </div>
              <div style="font-size:.68rem;color:{feat.color_fg}88;margin-bottom:5px">
                {len(feat.modules)} modules · {len(feat.classes)} classes · {len(feat.functions)} fonctions
              </div>
              <div style="margin-bottom:3px">{mod_pills}</div>
              <div>{cls_pills}</div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# GRAPHE D'EXÉCUTION ENRICHI (PyVis détaillé)
# ══════════════════════════════════════════════════════════

COLOR_MAP = {"module": "#58a6ff", "class": "#e3b341", "function": "#3fb950", "method": "#a5d6ff"}
SIZE_MAP = {"module": 30, "class": 22, "function": 18, "method": 14}


def build_enriched_graph(modules: list[ModuleInfo]) -> nx.DiGraph:
    """
    Construit un graphe dirigé ENRICHI avec :
    - Nœuds : modules, classes, fonctions, méthodes
    - Arêtes :
        * containment : module → classe, classe → méthode
        * calls : appels de fonctions
        * imports_module : import de module complet
        * imports_object : import d'objet spécifique (classe/fonction)
        * inherits : héritage de classes
    """
    G = nx.DiGraph()

    # Index global : nom → id complet
    global_index = {}

    # ── Phase 1 : Création des nœuds ──────────────────────
    for m in modules:
        # Module
        G.add_node(m.module_name,
                   kind="module",
                   label=m.module_name.split(".")[-1],
                   full=m.module_name,
                   filepath=m.filepath,
                   imports=m.imports[:5])

        # Fonctions
        for f in m.functions:
            fid = f"{m.module_name}.{f.name}"
            G.add_node(fid,
                       kind="function",
                       label=f.name,
                       full=fid,
                       lineno=f.lineno,
                       args=f.args,
                       is_async=f.is_async,
                       docstring=f.docstring or "")
            global_index[f.name] = fid
            G.add_edge(m.module_name, fid, kind="contains")

        # Classes
        for c in m.classes:
            cid = f"{m.module_name}.{c.name}"
            G.add_node(cid,
                       kind="class",
                       label=c.name,
                       full=cid,
                       bases=c.bases,
                       lineno=c.lineno,
                       docstring=c.docstring or "")
            global_index[c.name] = cid
            G.add_edge(m.module_name, cid, kind="contains")

            # Méthodes
            for mt in c.methods:
                mid = f"{cid}.{mt.name}"
                G.add_node(mid,
                           kind="method",
                           label=mt.name,
                           full=mid,
                           lineno=mt.lineno,
                           args=mt.args,
                           is_async=mt.is_async,
                           docstring=mt.docstring or "")
                global_index[f"{c.name}.{mt.name}"] = mid
                global_index[mt.name] = mid
                G.add_edge(cid, mid, kind="contains")

    # ── Phase 2 : Arêtes d'imports inter-modules ──────────
    module_exports = defaultdict(set)
    for m in modules:
        for c in m.classes:
            module_exports[m.module_name].add(c.name)
        for f in m.functions:
            module_exports[m.module_name].add(f.name)

    for m in modules:
        for imp in m.import_details:
            # Cherche le module source
            for other_mod in modules:
                if other_mod.module_name == imp.module:
                    # Import de module complet : import foo
                    if imp.name == imp.module:
                        G.add_edge(m.module_name, other_mod.module_name,
                                   kind="imports_module")
                    # Import d'objet : from foo import Bar
                    elif imp.name in module_exports[other_mod.module_name]:
                        target_id = f"{other_mod.module_name}.{imp.name}"
                        if target_id in G.nodes:
                            G.add_edge(m.module_name, target_id,
                                       kind="imports_object",
                                       alias=imp.alias)
                    break

    # ── Phase 3 : Arêtes d'appels ─────────────────────────
    for m in modules:
        all_funcs = list(m.functions) + [mt for c in m.classes for mt in c.methods]
        for f in all_funcs:
            src = global_index.get(f.name) or f"{m.module_name}.{f.name}"
            for called in f.calls:
                tgt = global_index.get(called) or global_index.get(called.split(".")[-1])
                if tgt and tgt != src:
                    G.add_edge(src, tgt, kind="calls")

    # ── Phase 4 : Arêtes d'héritage ───────────────────────
    for m in modules:
        for c in m.classes:
            cid = f"{m.module_name}.{c.name}"
            for base in c.bases:
                base_short = base.split(".")[-1]
                if base_short in global_index:
                    base_id = global_index[base_short]
                    if base_id != cid:
                        G.add_edge(base_id, cid, kind="inherits")

    return G


def build_enriched_pyvis_html(G: nx.DiGraph, height: int = 700) -> str:
    """Graphe PyVis enrichi avec 5 types d'arêtes différents"""
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:#f78166;padding:1rem'>⚠️ <code>pip install pyvis</code></p>"

    net = Network(height=f"{height}px", width="100%", directed=True,
                  bgcolor="#0d0f14", font_color="#c9d1d9")
    net.barnes_hut(gravity=-8000, central_gravity=0.3,
                   spring_length=120, spring_strength=0.04)

    for nid, data in G.nodes(data=True):
        kind = data.get("kind", "function")
        label = data.get("label", nid)
        lines = [f"<b>{data.get('full', nid)}</b>", f"Type : {kind}"]
        if data.get("lineno"):
            lines.append(f"Ligne : {data['lineno']}")
        if data.get("args"):
            lines.append(f"Args : {', '.join(data['args'])}")
        if data.get("docstring"):
            lines.append(f"📝 {data['docstring'][:80]}")
        if data.get("bases"):
            lines.append(f"Hérite : {', '.join(data['bases'])}")
        if data.get("imports"):
            lines.append(f"Imports : {', '.join(data['imports'])}")

        net.add_node(nid, label=label,
                     color=COLOR_MAP.get(kind, "#8b949e"),
                     size=SIZE_MAP.get(kind, 15),
                     title="<br>".join(lines),
                     font={"size": 11, "color": "#c9d1d9"},
                     borderWidth=2, borderWidthSelected=4)

    # 5 types d'arêtes avec couleurs différentes
    edge_colors = {
        "contains": "#30363d",  # gris (structure)
        "calls": "#f78166",  # rouge (appels)
        "imports_module": "#58a6ff",  # bleu (import module)
        "imports_object": "#79c0ff",  # bleu clair (import objet)
        "inherits": "#3fb950"  # vert (héritage)
    }

    for src, dst, data in G.edges(data=True):
        k = data.get("kind", "calls")
        color = edge_colors.get(k, "#8b949e")
        width = 2 if k in ["calls", "imports_object"] else 1
        dashes = (k == "contains")

        net.add_edge(src, dst,
                     color=color,
                     width=width,
                     arrows="to",
                     dashes=dashes,
                     title=k)

    net.set_options(json.dumps({
        "interaction": {"hover": True, "tooltipDelay": 150,
                        "navigationButtons": True, "keyboard": True},
        "physics": {"enabled": True},
        "edges": {"smooth": {"type": "dynamic"}},
    }))

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        return Path(f.name).read_text(encoding="utf-8")


def render_graph_tab(modules: list[ModuleInfo]):
    """Onglet graphe d'exécution enrichi"""

    with st.sidebar:
        st.markdown('<div class="section-hdr">🕸️ Graphe enrichi</div>', unsafe_allow_html=True)
        graph_h = st.slider("Hauteur (px)", 400, 1000, 680, 50, key="graph_h")
        filter_iso = st.checkbox("Masquer nœuds isolés", False, key="graph_iso")
        max_nodes = st.slider("Max nœuds", 20, 500, 200, 10, key="graph_max")

        st.markdown('<div class="section-hdr">🎨 Légende</div>', unsafe_allow_html=True)
        # Légende des nœuds
        for color, lbl in [("#58a6ff", "Module"), ("#e3b341", "Classe"),
                           ("#3fb950", "Fonction"), ("#a5d6ff", "Méthode")]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;'
                f'font-size:.8rem;color:#c9d1d9">'
                f'<span style="width:12px;height:12px;border-radius:50%;'
                f'background:{color};display:inline-block"></span>{lbl}</div>',
                unsafe_allow_html=True)

        st.markdown("**Arêtes**")
        st.markdown(
            '<div style="font-size:.75rem;color:#8b949e;line-height:1.6">'
            '<span style="color:#30363d">━━</span> Containment<br>'
            '<span style="color:#f78166">━━</span> Appels<br>'
            '<span style="color:#58a6ff">━━</span> Import module<br>'
            '<span style="color:#79c0ff">━━</span> Import objet<br>'
            '<span style="color:#3fb950">━━</span> Héritage'
            '</div>',
            unsafe_allow_html=True)

    # Construire le graphe enrichi
    G = build_enriched_graph(modules)

    if filter_iso:
        G.remove_nodes_from(list(nx.isolates(G)))

    if len(G.nodes) > max_nodes:
        top = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)[:max_nodes]
        G = G.subgraph(top).copy()
        st.info(f"ℹ️ Limité aux {max_nodes} nœuds les plus connectés.")

    st.markdown(
        f"<small style='color:#8b949e'>"
        f"<b style='color:#c9d1d9'>{G.number_of_nodes()}</b> nœuds · "
        f"<b style='color:#c9d1d9'>{G.number_of_edges()}</b> arêtes</small>",
        unsafe_allow_html=True)

    components.html(build_enriched_pyvis_html(G, height=graph_h),
                    height=graph_h + 30, scrolling=False)


# ══════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════

st.markdown("# 🔬 Python Code Intelligence")
st.markdown(
    "<p style='color:#8b949e;margin-top:-10px;font-size:.95rem'>"
    "Graphe enrichi · Features Louvain · Diagrammes UML</p>",
    unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 📂 Projet")
    project_path = st.text_input(
        "Chemin du projet", value=".",
        help="Chemin absolu ou relatif vers le dossier racine",
        key="project_path")
    run = st.button("🚀 Analyser", use_container_width=True)
    st.markdown("---")
    st.markdown(
        "<small style='color:#8b949e'>Dépendances :<br>"
        "<code>pip install streamlit networkx pyvis</code></small>",
        unsafe_allow_html=True)

if run or "modules" in st.session_state:
    if run:
        with st.spinner("Analyse du projet…"):
            try:
                mods = parse_project(project_path)
                st.session_state["modules"] = mods
                st.session_state["cross_rels"] = build_cross_relations(mods)
                st.session_state.pop("features", None)
                st.session_state["path_ok"] = project_path
            except (FileNotFoundError, NotADirectoryError) as e:
                st.error(f"❌ {e}");
                st.stop()

    modules: list[ModuleInfo] = st.session_state.get("modules", [])
    cross_rels: list[CrossRelation] = st.session_state.get("cross_rels", [])
    features: list[Feature] = st.session_state.get("features", [])

    if not modules:
        st.warning("Aucun fichier Python analysable trouvé.");
        st.stop()

    feat_label = f"🧩 Features ({len(features)})" if features else "🧩 Features"
    tab_feat, tab_graph, tab_uml = st.tabs([
        feat_label,
        "🕸️ Graphe d'exécution",
        "📐 Diagrammes UML",
    ])
    with tab_feat:
        render_features_tab(modules, cross_rels)
    with tab_graph:
        render_graph_tab(modules)
    with tab_uml:
        st.info("📐 UML : intégrez votre code UML ici")

else:
    st.markdown("""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;
                padding:2.5rem 3rem;max-width:620px;margin:3rem auto;text-align:center">
        <div style="font-size:3.5rem">🔬</div>
        <h2 style="color:#58a6ff;font-family:'Syne',sans-serif;margin:.5rem 0">
            Python Code Intelligence</h2>
        <div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin:1.5rem 0">
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:140px;text-align:center">
                <div style="font-size:1.8rem">🧩</div>
                <div style="color:#c678dd;font-weight:600;font-size:.85rem;margin:.3rem 0">
                    Features Louvain</div>
                <div style="color:#8b949e;font-size:.75rem">Clustering avec<br>imports réels</div>
            </div>
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:140px;text-align:center">
                <div style="font-size:1.8rem">🕸️</div>
                <div style="color:#58a6ff;font-weight:600;font-size:.85rem;margin:.3rem 0">
                    Graphe enrichi</div>
                <div style="color:#8b949e;font-size:.75rem">Appels · containment<br>imports réels</div>
            </div>
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:140px;text-align:center">
                <div style="font-size:1.8rem">📐</div>
                <div style="color:#e3b341;font-weight:600;font-size:.85rem;margin:.3rem 0">
                    UML cross-module</div>
                <div style="color:#8b949e;font-size:.75rem">Héritage · associations<br>appels inter-fichiers</div>
            </div>
        </div>
        <hr style="border:none;border-top:1px solid #30363d;margin:1.2rem 0">
        <p style="color:#8b949e;font-size:.78rem;margin:0">
            Entrez un chemin dans la sidebar · cliquez
            <b style="color:#c9d1d9">🚀 Analyser</b>
        </p>
    </div>
    """, unsafe_allow_html=True)