"""
app_python_explorer_v2.py — Python Code Intelligence
══════════════════════════════════════════════════════
2 vues : Graphe d'exécution + Diagrammes UML cross-module
UML : détecte héritage, associations et appels entre classes
de fichiers différents.

Dépendances : pip install streamlit networkx pyvis
"""

import ast
import base64
import html as html_lib
import json
import tempfile
import textwrap
import zlib
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

.badge { display:inline-block; padding:2px 8px; border-radius:20px;
         font-size:.72rem; font-weight:600; margin:1px;
         font-family:'JetBrains Mono',monospace; }
.bf  { background:#1f4068; color:#58a6ff; }
.bc  { background:#3b2f0e; color:#e3b341; }
.ba  { background:#1b2d1b; color:#3fb950; }
.bi  { background:#2d1b2d; color:#d2a8ff; }
.bx  { background:#1e2828; color:#56d364; }

.cpill { display:inline-block; padding:3px 10px; border-radius:20px;
         font-size:.73rem; font-weight:500; margin:2px;
         font-family:'JetBrains Mono',monospace; }
.pc  { background:#1a2744; color:#79c0ff; }
.pm  { background:#2d2506; color:#e3b341; }
.pi  { background:#0d2818; color:#3fb950; }
.pas { background:#2d1020; color:#f778ba; }
.pcross { background:#1e1e2e; color:#c678dd; }

.legend-row { display:flex; align-items:center; gap:8px;
              margin:4px 0; font-size:.8rem; color:#c9d1d9; }
.dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
.section-hdr {
    font-family:'Syne',sans-serif; font-size:1rem; font-weight:600;
    color:#58a6ff; border-bottom:1px solid #30363d;
    padding-bottom:5px; margin:1rem 0 .7rem;
}
.rel-badge {
    display:inline-block; padding:2px 8px; border-radius:4px;
    font-size:.7rem; font-family:'JetBrains Mono',monospace; margin:1px;
}
.rel-inherit { background:#0d2818; color:#56d364; }
.rel-assoc   { background:#1a2744; color:#79c0ff; }
.rel-use     { background:#2d2506; color:#e3b341; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ══════════════════════════════════════════════════════════
@dataclass
class FunctionInfo:
    name: str; lineno: int; end_lineno: int
    args: list[str]; docstring: Optional[str]
    calls: list[str]; is_async: bool
    node: ast.FunctionDef

@dataclass
class ClassInfo:
    name: str; lineno: int; end_lineno: int
    bases: list[str]; decorators: list[str]; docstring: Optional[str]
    methods: list[FunctionInfo] = field(default_factory=list)
    node: ast.ClassDef = None

@dataclass
class ModuleInfo:
    filepath: str; module_name: str; docstring: Optional[str]
    imports: list[str]; functions: list[FunctionInfo]
    classes: list[ClassInfo]; source_lines: list[str]


# ══════════════════════════════════════════════════════════
# PARSER
# ══════════════════════════════════════════════════════════
EXCLUDE_DIRS = {
    ".git",".venv","venv","env","__pycache__",".tox","dist",
    "build",".mypy_cache",".pytest_cache","node_modules",".eggs",
}

def collect_py_files(project_path: str) -> list[Path]:
    root = Path(project_path).resolve()
    if not root.exists():  raise FileNotFoundError(f"Introuvable : {root}")
    if not root.is_dir():  raise NotADirectoryError(f"Pas un dossier : {root}")
    return sorted(p for p in root.rglob("*.py")
                  if not any(ex in p.parts for ex in EXCLUDE_DIRS))

def read_file(fp: Path) :
    try:    return fp.read_text(encoding="utf-8", errors="replace")
    except OSError: return None

def parse_source(src: str, fname: str = "<unknown>"):
    try:    return ast.parse(src, filename=fname)
    except SyntaxError: return None

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
        end_lineno=getattr(node,"end_lineno",node.lineno),
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
            end_lineno=getattr(node,"end_lineno",node.lineno),
            bases=[_resolve_name(b) or ast.unparse(b) for b in node.bases],
            decorators=[_resolve_name(d) or ast.unparse(d) for d in node.decorator_list],
            docstring=ast.get_docstring(node),
            methods=[_build_func(c) for c in ast.iter_child_nodes(node)
                     if isinstance(c,(ast.FunctionDef,ast.AsyncFunctionDef))],
            node=node,
        ))
    return out

def extract_attributes(class_node: ast.ClassDef) -> list[tuple[str,str]]:
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
                            try: tp = ast.unparse(stmt.annotation)
                            except Exception: tp = "Any"
                            attrs.append((nm,tp)); seen.add(nm)
                elif isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if (isinstance(t, ast.Attribute) and
                                isinstance(t.value, ast.Name) and
                                t.value.id == "self" and t.attr not in seen):
                            attrs.append((t.attr,"")); seen.add(t.attr)
    return attrs

def parse_one_file(fp: Path, root: Path) :
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
        functions=extract_functions(tree),
        classes=extract_classes(tree),
        source_lines=src.splitlines(keepends=True),
    )

@st.cache_data(show_spinner=False)
def parse_project(project_path: str) -> list[ModuleInfo]:
    root  = Path(project_path).resolve()
    files = collect_py_files(project_path)
    out   = []
    for fp in files:
        m = parse_one_file(fp, root)
        if m: out.append(m)
    return out


# ══════════════════════════════════════════════════════════
# ANALYSE DES RELATIONS INTER-MODULES
# ══════════════════════════════════════════════════════════

@dataclass
class CrossRelation:
    """Une relation entre deux classes de modules différents."""
    kind:       str   # "inherits" | "associates" | "uses"
    src_module: str
    src_class:  str
    dst_module: str
    dst_class:  str
    label:      str   # nom attribut / méthode / base


def build_cross_relations(modules: list[ModuleInfo]) -> list[CrossRelation]:
    """
    Détecte 3 types de relations inter-modules :
    1. Héritage       : class Dog(Animal) où Animal est dans un autre module
    2. Association    : self.engine = Engine(...)  — attribut typé vers une autre classe
    3. Utilisation    : appel de méthode ou instanciation dans une méthode
    """
    # Index global : nom_classe → module_name
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
            # ── 1. Héritage cross-module ──────────────────
            for base in cls.bases:
                base_short = base.split(".")[-1]
                if base_short in global_cls and base_short not in local_cls:
                    add("inherits", m.module_name, cls.name,
                        global_cls[base_short], base_short, base_short)

            # ── 2. Association via attributs typés ────────
            if cls.node:
                for attr_name, attr_type in extract_attributes(cls.node):
                    # cherche chaque nom de classe connu dans le type
                    for known_cls, known_mod in global_cls.items():
                        if known_cls in attr_type and known_cls not in local_cls:
                            add("associates", m.module_name, cls.name,
                                known_mod, known_cls, attr_name)

            # ── 3. Utilisation via appels de méthodes ─────
            for mt in cls.methods:
                for call in mt.calls:
                    # Détecte : ClassName(...) ou instance.method()
                    root_name = call.split(".")[0]
                    if root_name in global_cls and root_name not in local_cls:
                        add("uses", m.module_name, cls.name,
                            global_cls[root_name], root_name, f"{mt.name}→{call}")

    return relations


# ══════════════════════════════════════════════════════════
# VUE ①  —  GRAPHE D'EXÉCUTION (PyVis)
# ══════════════════════════════════════════════════════════

COLOR_MAP = {"module":"#58a6ff","class":"#e3b341","function":"#3fb950","method":"#a5d6ff"}
SIZE_MAP  = {"module":30,"class":22,"function":18,"method":14}

def build_call_graph(modules: list[ModuleInfo], mode: str = "calls") -> nx.DiGraph:
    G, idx = nx.DiGraph(), {}
    for m in modules:
        G.add_node(m.module_name, kind="module", label=m.module_name.split(".")[-1],
                   full=m.module_name, filepath=m.filepath, imports=m.imports[:5])
        for f in m.functions:
            fid = f"{m.module_name}.{f.name}"
            G.add_node(fid, kind="function", label=f.name, full=fid,
                       lineno=f.lineno, args=f.args, is_async=f.is_async,
                       docstring=f.docstring or "")
            idx[f.name] = fid
            if mode in ("contains","both"): G.add_edge(m.module_name, fid, kind="contains")
        for c in m.classes:
            cid = f"{m.module_name}.{c.name}"
            G.add_node(cid, kind="class", label=c.name, full=cid,
                       bases=c.bases, lineno=c.lineno, docstring=c.docstring or "")
            if mode in ("contains","both"): G.add_edge(m.module_name, cid, kind="contains")
            for mt in c.methods:
                mid = f"{cid}.{mt.name}"
                G.add_node(mid, kind="method", label=mt.name, full=mid,
                           lineno=mt.lineno, args=mt.args,
                           is_async=mt.is_async, docstring=mt.docstring or "")
                idx[f"{c.name}.{mt.name}"] = mid; idx[mt.name] = mid
                if mode in ("contains","both"): G.add_edge(cid, mid, kind="contains")
    if mode in ("calls","both"):
        for m in modules:
            for f in list(m.functions) + [mt for c in m.classes for mt in c.methods]:
                src = idx.get(f.name) or f"{m.module_name}.{f.name}"
                for called in f.calls:
                    tgt = idx.get(called) or idx.get(called.split(".")[-1])
                    if tgt and tgt != src: G.add_edge(src, tgt, kind="calls")
    return G

def build_pyvis_html(G: nx.DiGraph, height: int = 700) -> str:
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:#f78166;padding:1rem'>⚠️ <code>pip install pyvis</code></p>"
    net = Network(height=f"{height}px", width="100%", directed=True,
                  bgcolor="#0d0f14", font_color="#c9d1d9")
    net.barnes_hut(gravity=-8000, central_gravity=0.3,
                   spring_length=120, spring_strength=0.04)
    for nid, data in G.nodes(data=True):
        kind  = data.get("kind","function")
        label = data.get("label", nid)
        lines = [f"<b>{data.get('full',nid)}</b>", f"Type : {kind}"]
        if data.get("lineno"):    lines.append(f"Ligne : {data['lineno']}")
        if data.get("args"):      lines.append(f"Args : {', '.join(data['args'])}")
        if data.get("docstring"): lines.append(f"📝 {data['docstring'][:80]}")
        if data.get("bases"):     lines.append(f"Hérite : {', '.join(data['bases'])}")
        if data.get("imports"):   lines.append(f"Imports : {', '.join(data['imports'])}")
        net.add_node(nid, label=label,
                     color=COLOR_MAP.get(kind,"#8b949e"),
                     size=SIZE_MAP.get(kind,15),
                     title="<br>".join(lines),
                     font={"size":11,"color":"#c9d1d9"},
                     borderWidth=2, borderWidthSelected=4)
    for src, dst, data in G.edges(data=True):
        k = data.get("kind","calls")
        net.add_edge(src, dst,
                     color={"contains":"#30363d","calls":"#f78166"}.get(k,"#8b949e"),
                     width=2 if k=="calls" else 1, arrows="to",
                     dashes=(k=="contains"), title=k)
    net.set_options(json.dumps({
        "interaction":{"hover":True,"tooltipDelay":150,
                       "navigationButtons":True,"keyboard":True},
        "physics":{"enabled":True},
        "edges":{"smooth":{"type":"dynamic"}},
    }))
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        return Path(f.name).read_text(encoding="utf-8")


def render_module_details(modules: list[ModuleInfo]):
    """Accordéon détail des modules — partagé par les deux onglets."""
    st.markdown('<div class="section-hdr">📋 Détail des modules</div>',
                unsafe_allow_html=True)
    for m in modules:
        with st.expander(f"📄 `{m.module_name}`  "
                         f"({len(m.classes)} classes · {len(m.functions)} fonctions)"):
            if m.docstring:
                st.markdown(f"> {m.docstring}")
            if m.imports:
                badges = " ".join(
                    f'<span class="badge bi">{i.split(".")[-1]}</span>'
                    for i in m.imports[:14])
                st.markdown(f"**Imports** : {badges}", unsafe_allow_html=True)

            col_f, col_c = st.columns(2)
            with col_f:
                if m.functions:
                    st.markdown("**Fonctions top-level**")
                    for f in m.functions:
                        ab = '<span class="badge ba">async</span>' if f.is_async else ""
                        doc = textwrap.shorten(f.docstring or "–", 70)
                        calls_s = ", ".join(f.calls[:4]) or "–"
                        st.markdown(
                            f'<span class="badge bf">{f.name}</span> {ab} '
                            f'`L{f.lineno}`<br>'
                            f'<small style="color:#8b949e">📝 {doc}</small><br>'
                            f'<small style="color:#8b949e">📞 {calls_s}</small>',
                            unsafe_allow_html=True)
            with col_c:
                if m.classes:
                    st.markdown("**Classes**")
                    for c in m.classes:
                        bases_s = f" ⇑ `{', '.join(c.bases)}`" if c.bases and c.bases != ["object"] else ""
                        st.markdown(
                            f'<span class="badge bc">{c.name}</span>{bases_s} '
                            f'`L{c.lineno}`',
                            unsafe_allow_html=True)
                        for mt in c.methods[:6]:
                            ab = '<span class="badge ba" style="font-size:.6rem">async</span>' if mt.is_async else ""
                            st.markdown(
                                f'&nbsp;&nbsp;↳ <span class="badge bf" style="font-size:.65rem">'
                                f'{mt.name}</span> {ab} `L{mt.lineno}`',
                                unsafe_allow_html=True)


def render_graph_tab(modules: list[ModuleInfo]):
    # ── Sidebar section Graphe (simplifié) ────────────────
    with st.sidebar:
        st.markdown('<div class="section-hdr">🕸️ Graphe</div>', unsafe_allow_html=True)
        graph_h    = st.slider("Hauteur (px)", 400, 1000, 680, 50, key="graph_h")
        filter_iso = st.checkbox("Masquer nœuds isolés", False, key="graph_iso")
        max_nodes  = st.slider("Max nœuds", 20, 500, 200, 10, key="graph_max")

        st.markdown('<div class="section-hdr">🎨 Légende</div>', unsafe_allow_html=True)
        for color, lbl in [("#58a6ff","Module"),("#e3b341","Classe"),
                           ("#3fb950","Fonction"),("#a5d6ff","Méthode")]:
            st.markdown(
                f'<div class="legend-row"><span class="dot" style="background:{color}"></span>{lbl}</div>',
                unsafe_allow_html=True)
        st.markdown(
            '<div class="legend-row"><span style="color:#f78166;font-size:1.1rem">→</span> Appel</div>'
            '<div class="legend-row"><span style="color:#444;font-size:1.1rem">⇢</span> Containment</div>',
            unsafe_allow_html=True)

    # ── Graphe (toujours en mode "both") ──────────────────
    G = build_call_graph(modules, mode="both")
    if filter_iso: G.remove_nodes_from(list(nx.isolates(G)))
    if len(G.nodes) > max_nodes:
        top = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)[:max_nodes]
        G   = G.subgraph(top).copy()
        st.info(f"ℹ️ Limité aux {max_nodes} nœuds les plus connectés.")

    st.markdown(
        f"<small style='color:#8b949e'>"
        f"<b style='color:#c9d1d9'>{G.number_of_nodes()}</b> nœuds · "
        f"<b style='color:#c9d1d9'>{G.number_of_edges()}</b> arêtes</small>",
        unsafe_allow_html=True)

    components.html(build_pyvis_html(G, height=graph_h),
                    height=graph_h + 30, scrolling=False)

    st.divider()
    render_module_details(modules)


# ══════════════════════════════════════════════════════════
# VUE ②  —  UML CROSS-MODULE (Mermaid)
# ══════════════════════════════════════════════════════════

MERMAID_TPL = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
  body{{margin:0;padding:0;background:#0d1117;}}
  #diagram{{padding:1rem;min-height:200px;}}
  .mermaid{{font-family:'JetBrains Mono',monospace!important;}}
</style></head><body>
<div id="diagram"><pre class="mermaid">{mermaid_code}</pre></div>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{startOnLoad:true,theme:'{theme}',
    classDiagram:{{diagramPadding:20,htmlLabels:false}},
    securityLevel:'loose',fontFamily:'JetBrains Mono,monospace',fontSize:13}});
</script></body></html>"""

def render_mermaid(code: str, height: int = 600, theme: str = "dark"):
    escaped = html_lib.escape(code, quote=False)
    components.html(MERMAID_TPL.format(mermaid_code=escaped, theme=theme),
                    height=height, scrolling=True)

def _san(n: str) -> str:
    return n.replace(".","_").replace("-","_").replace("<","").replace(">","")

def _vis(n: str) -> str:
    if n.startswith("__") and not n.endswith("__"): return "-"
    if n.startswith("_"): return "#"
    return "+"

def _fmt(t: str) -> str:
    if not t: return ""
    for k, v in {"Optional[":"?","list[":"list~","dict[":"dict~",
                 "tuple[":"tuple~","set[":"set~"}.items():
        t = t.replace(k, v)
    if "~" in t: t = t.replace("]","~")
    return t[:28]

def mermaid_live_url(code: str, theme: str) -> str:
    state = json.dumps({"code": code, "mermaid": {"theme": theme}})
    enc   = base64.urlsafe_b64encode(zlib.compress(state.encode(), 9)).decode()
    return f"https://mermaid.live/edit#pako:{enc}"


def gen_mermaid_crossmodule(
    modules: list[ModuleInfo],
    selected: list[str],
    cross_rels: list[CrossRelation],
    *,
    attrs: bool = True,
    methods: bool = True,
    private: bool = False,
    show_inherit: bool = True,
    show_assoc: bool = True,
    show_uses: bool = True,
) -> str:
    """
    Génère un classDiagram Mermaid global avec :
    - namespaces par module
    - relations inter-modules : héritage, association, utilisation
    """
    filtered = [m for m in modules if m.module_name in selected]
    if not filtered: return "classDiagram"

    # Index : nom_classe → module_name (scope sélectionné)
    sel_cls: dict[str,str] = {}
    for m in filtered:
        for c in m.classes:
            sel_cls[c.name] = m.module_name

    lines = ["classDiagram"]

    # ── Déclaration des classes par namespace ─────────────
    for m in filtered:
        if not m.classes: continue
        ns = _san(m.module_name.split(".")[-1])
        lines.append(f"    namespace {ns} {{")
        for cls in m.classes:
            cn = _san(cls.name)
            lines.append(f"        class {cn} {{")
            # stéréotypes
            if "ABC" in cls.bases or "abc.ABC" in cls.bases:
                lines.append("            <<abstract>>")
            elif cls.decorators and "dataclass" in " ".join(cls.decorators):
                lines.append("            <<dataclass>>")
            elif "Protocol" in cls.bases:
                lines.append("            <<interface>>")
            # attributs
            if attrs and cls.node:
                for an, at in extract_attributes(cls.node)[:6]:
                    if not private and an.startswith("_"): continue
                    ts = f" {_fmt(at)}" if at else ""
                    lines.append(f"            {_vis(an)}{an}{ts}")
            # méthodes
            if methods:
                for mt in cls.methods[:8]:
                    if not private and mt.name.startswith("_") and mt.name != "__init__":
                        continue
                    args = ", ".join(a for a in mt.args if a != "self")[:32]
                    ret = ""
                    if mt.node and mt.node.returns:
                        try: ret = f" {_fmt(ast.unparse(mt.node.returns))}"
                        except Exception: pass
                    ap = "async " if mt.is_async else ""
                    lines.append(f"            {_vis(mt.name)}{ap}{mt.name}({args}){ret}")
            lines.append("        }")
        lines.append("    }")

    lines.append("")
    lines.append("    %% ── Relations intra-module ──")

    # ── Relations INTRA-module ────────────────────────────
    for m in filtered:
        local_names = {c.name for c in m.classes}
        for cls in m.classes:
            cn = _san(cls.name)
            # héritage interne
            for b in cls.bases:
                if b in local_names:
                    lines.append(f"    {_san(b)} <|-- {cn}")
            # association interne via attributs
            if attrs and cls.node:
                for an, at in extract_attributes(cls.node):
                    for oc in m.classes:
                        if oc.name != cls.name and oc.name in at:
                            lines.append(f"    {cn} --> {_san(oc.name)} : {an}")
                            break

    lines.append("")
    lines.append("    %% ── Relations inter-modules ──")

    # ── Relations INTER-modules (cross_rels filtrés) ──────
    shown_cross: set[tuple] = set()
    for rel in cross_rels:
        # ne garder que les relations entre modules sélectionnés
        if rel.src_module not in selected or rel.dst_module not in selected:
            continue
        src_cn = _san(rel.src_class)
        dst_cn = _san(rel.dst_class)
        key    = (rel.kind, src_cn, dst_cn)
        if key in shown_cross: continue
        shown_cross.add(key)

        if rel.kind == "inherits" and show_inherit:
            lines.append(f"    {dst_cn} <|-- {src_cn} : hérite")
        elif rel.kind == "associates" and show_assoc:
            label = rel.label[:20]
            lines.append(f"    {src_cn} --> {dst_cn} : {label}")
        elif rel.kind == "uses" and show_uses:
            label = rel.label.split("→")[-1][:18]
            lines.append(f"    {src_cn} ..> {dst_cn} : {label}")

    return "\n".join(lines)


def render_uml_tab(modules: list[ModuleInfo], cross_rels: list[CrossRelation]):
    mwc = [m for m in modules if m.classes]
    all_classes = [c for m in modules for c in m.classes]
    all_methods = [mt for c in all_classes for mt in c.methods]

    # ── Sidebar section UML (simplifié) ───────────────────
    with st.sidebar:
        st.markdown('<div class="section-hdr">📐 UML</div>', unsafe_allow_html=True)
        show_attrs  = st.checkbox("Attributs",          True,  key="uml_attrs")
        show_meths  = st.checkbox("Méthodes",           True,  key="uml_meths")
        show_priv   = st.checkbox("Membres privés (_)", False, key="uml_priv")
        st.markdown("**Relations inter-modules**")
        show_inh    = st.checkbox("Héritage cross-mod",    True,  key="uml_inh")
        show_assoc  = st.checkbox("Associations cross-mod", True,  key="uml_assoc")
        show_uses   = st.checkbox("Utilisations cross-mod", True,  key="uml_uses")
        uml_h       = st.slider("Hauteur (px)", 300, 1400, 680, 50, key="uml_h")

        st.markdown('<div class="section-hdr">📖 Notation</div>', unsafe_allow_html=True)
        st.markdown(
            "`+` public &nbsp;`#` protégé &nbsp;`-` privé  \n"
            "`<|--` héritage &nbsp;`-->` association  \n"
            "`..>` utilisation &nbsp;`<<abstract>>`")

    # ── Métriques supprimées (plus de KPI) ───────────────

    if not mwc:
        st.warning("Aucun module ne contient de classes.")
        return

    # ── Panneau des relations cross-module ─────────────────
    nb_cross = len(cross_rels)
    if cross_rels:
        with st.expander(f"🔗 Relations inter-modules détectées ({nb_cross})", expanded=False):
            for rel in cross_rels:
                kind_badge = {
                    "inherits":  '<span class="rel-badge rel-inherit">héritage</span>',
                    "associates":'<span class="rel-badge rel-assoc">association</span>',
                    "uses":      '<span class="rel-badge rel-use">utilisation</span>',
                }.get(rel.kind, "")
                st.markdown(
                    f'{kind_badge} '
                    f'<code>{rel.src_module.split(".")[-1]}</code>.<span class="badge bc">{rel.src_class}</span>'
                    f' → '
                    f'<code>{rel.dst_module.split(".")[-1]}</code>.<span class="badge bc">{rel.dst_class}</span>'
                    f' <small style="color:#8b949e">({rel.label})</small>',
                    unsafe_allow_html=True)

    st.divider()

    # ── Sélection des modules à inclure ───────────────────
    opts     = [m.module_name for m in mwc]
    selected = st.multiselect(
        "Modules à inclure dans le diagramme",
        options=opts,
        default=opts[:min(len(opts), 10)],
        help="Sélectionnez les modules à afficher. Les relations inter-modules "
             "ne sont tracées qu'entre les modules sélectionnés.",
        key="uml_sel",
    )
    if not selected:
        st.info("Sélectionnez au moins un module.")
        return

    # ── Génération du code Mermaid (toujours en dark) ─────
    code = gen_mermaid_crossmodule(
        modules, selected, cross_rels,
        attrs=show_attrs, methods=show_meths, private=show_priv,
        show_inherit=show_inh, show_assoc=show_assoc, show_uses=show_uses,
    )

    if code.strip() in ("classDiagram", "classDiagram\n"):
        st.warning("Aucune classe dans la sélection.")
        return

    # ── Onglets internes : Diagramme / Code / Détail ──────
    t1, t2, t3 = st.tabs(["📊 Diagramme", "💻 Code Mermaid", "🔍 Détail des classes"])

    with t1:
        # Légende des relations cross-module affichées
        active_rels = [r for r in cross_rels
                       if r.src_module in selected and r.dst_module in selected]
        if active_rels:
            kinds = {r.kind for r in active_rels}
            legend_parts = []
            if "inherits"  in kinds: legend_parts.append('<span class="rel-badge rel-inherit">▸ héritage</span>')
            if "associates" in kinds: legend_parts.append('<span class="rel-badge rel-assoc">▸ association</span>')
            if "uses"       in kinds: legend_parts.append('<span class="rel-badge rel-use">▸ utilisation</span>')
            st.markdown(
                f"Relations inter-modules visibles : {' '.join(legend_parts)}",
                unsafe_allow_html=True)
        render_mermaid(code, height=uml_h, theme="dark")

    with t2:
        st.code(code, language="text")
        c1, c2 = st.columns([1,3])
        with c1:
            st.download_button("⬇️ .mmd", data=code,
                               file_name="uml_crossmodule.mmd", mime="text/plain")
        with c2:
            st.markdown(
                f'<a href="{mermaid_live_url(code, "dark")}" target="_blank" '
                f'style="font-size:.85rem;color:#58a6ff">🔗 Ouvrir dans Mermaid Live</a>',
                unsafe_allow_html=True)

    with t3:
        # Détail par module sélectionné
        for m in [mod for mod in mwc if mod.module_name in selected]:
            st.markdown(
                f'<div class="section-hdr">📄 {m.module_name}</div>',
                unsafe_allow_html=True)
            for cls in m.classes:
                # Relations cross-module impliquant cette classe
                cls_rels = [r for r in cross_rels
                            if (r.src_class == cls.name or r.dst_class == cls.name)
                            and r.src_module in selected and r.dst_module in selected]

                with st.expander(f"🏛️ `{cls.name}`", expanded=False):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Lignes** `{cls.lineno}–{cls.end_lineno}`")
                        if cls.bases and cls.bases != ["object"]:
                            st.markdown(f"**Hérite** `{', '.join(cls.bases)}`")
                        if cls.decorators:
                            st.markdown(f"**Décorateurs** `{', '.join(cls.decorators)}`")
                        if cls.docstring:
                            st.info(cls.docstring)
                        # Attributs
                        if cls.node:
                            attrs_list = extract_attributes(cls.node)
                            if attrs_list:
                                st.markdown("**Attributs**")
                                for an, at in attrs_list:
                                    ts = f" : `{at}`" if at else ""
                                    st.markdown(
                                        f'&nbsp;&nbsp;<span class="badge bx">{an}</span>{ts}',
                                        unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"**{len(cls.methods)} méthodes**")
                        for mt in cls.methods:
                            icon = "⚡" if mt.is_async else "◆"
                            args = ", ".join(a for a in mt.args if a != "self")
                            doc  = textwrap.shorten(mt.docstring or "–", 55)
                            st.markdown(
                                f"{icon} `{mt.name}({args})` L{mt.lineno}  \n"
                                f"<small style='color:#8b949e'>{doc}</small>",
                                unsafe_allow_html=True)

                        # Relations cross-module de cette classe
                        if cls_rels:
                            st.markdown("**Relations inter-modules**")
                            for rel in cls_rels:
                                arrow = "→" if rel.src_class == cls.name else "←"
                                other = rel.dst_class if rel.src_class == cls.name else rel.src_class
                                other_mod = rel.dst_module if rel.src_class == cls.name else rel.src_module
                                kind_b = {
                                    "inherits":  '<span class="rel-badge rel-inherit">hérite</span>',
                                    "associates":'<span class="rel-badge rel-assoc">associe</span>',
                                    "uses":      '<span class="rel-badge rel-use">utilise</span>',
                                }.get(rel.kind, "")
                                st.markdown(
                                    f'&nbsp;&nbsp;{kind_b} {arrow} '
                                    f'<code>{other_mod.split(".")[-1]}</code>.'
                                    f'<span class="badge bc">{other}</span> '
                                    f'<small style="color:#8b949e">({rel.label})</small>',
                                    unsafe_allow_html=True)

    st.divider()
    # Grille rapide de tous les modules avec classes
    st.markdown('<div class="section-hdr">📋 Tous les modules avec classes</div>',
                unsafe_allow_html=True)
    cols = st.columns(3)
    for i, m in enumerate(mwc):
        with cols[i % 3]:
            cls_list = " ".join(
                f'<span class="badge bc">{c.name}</span>' for c in m.classes)
            in_sel = "✓" if m.module_name in selected else ""
            st.markdown(
                f"**{m.module_name.split('.')[-1]}** {in_sel}  \n"
                f"<small style='color:#8b949e'>{m.module_name}</small>  \n"
                f"{cls_list}",
                unsafe_allow_html=True)

    st.divider()
    render_module_details(modules)


# ══════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════

st.markdown("# 🔬 Retrodoc")
st.markdown(
    "<p style='color:#8b949e;margin-top:-10px;font-size:.95rem'>"
    "Graphe d'exécution · Diagrammes UML cross-module</p>",
    unsafe_allow_html=True)

# ── Sidebar : projet ──────────────────────────────────────
with st.sidebar:
    st.markdown("## 📂 Projet")
    project_path = st.text_input(
        "Chemin du projet", value=".",
        help="Chemin absolu ou relatif vers le dossier racine",
        key="project_path")
    run = st.button("🚀 Analyser", use_container_width=True)
    st.markdown("---")

# ── Analyse + cache ───────────────────────────────────────
if run or "modules" in st.session_state:
    if run:
        with st.spinner("Analyse du projet…"):
            try:
                mods = parse_project(project_path)
                st.session_state["modules"]    = mods
                st.session_state["cross_rels"] = build_cross_relations(mods)
                st.session_state["path_ok"]    = project_path
            except (FileNotFoundError, NotADirectoryError) as e:
                st.error(f"❌ {e}"); st.stop()

    modules:    list[ModuleInfo]    = st.session_state.get("modules", [])
    cross_rels: list[CrossRelation] = st.session_state.get("cross_rels", [])

    if not modules:
        st.warning("Aucun fichier Python analysable trouvé."); st.stop()

    # ── 2 onglets ─────────────────────────────────────────
    tab_graph, tab_uml = st.tabs([
        "🕸️ Graphe d'exécution",
        "📐 Diagrammes UML",
    ])
    with tab_graph: render_graph_tab(modules)
    with tab_uml:   render_uml_tab(modules, cross_rels)

else:
    st.markdown("""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;
                padding:2.5rem 3rem;max-width:580px;margin:3rem auto;text-align:center">
        <div style="font-size:3.5rem">🔬</div>
        <h2 style="color:#58a6ff;font-family:'Syne',sans-serif;margin:.5rem 0">
            Python Code Intelligence</h2>
        <div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin:1.5rem 0">
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:150px">
                <div style="font-size:1.8rem">🕸️</div>
                <div style="color:#58a6ff;font-weight:600;font-size:.9rem;margin:.3rem 0">
                    Graphe d'exécution</div>
                <div style="color:#8b949e;font-size:.78rem">Appels, containment,<br>nœuds interactifs</div>
            </div>
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:150px">
                <div style="font-size:1.8rem">📐</div>
                <div style="color:#e3b341;font-weight:600;font-size:.9rem;margin:.3rem 0">
                    UML cross-module</div>
                <div style="color:#8b949e;font-size:.78rem">Héritage, associations<br>et appels inter-fichiers</div>
            </div>
        </div>
        <hr style="border:none;border-top:1px solid #30363d;margin:1.2rem 0">
        <p style="color:#8b949e;font-size:.78rem;margin:0">
            Entrez un chemin dans la sidebar · cliquez <b style="color:#c9d1d9">🚀 Analyser</b>
        </p>
    </div>
    """, unsafe_allow_html=True)