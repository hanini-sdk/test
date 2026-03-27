"""
app_python_explorer.py — Python Code Intelligence Suite
═══════════════════════════════════════════════════════
Regroupe deux visions complémentaires d'un projet Python :
  ① Graphe d'exécution  — appels de fonctions (PyVis / NetworkX)
  ② Diagrammes UML      — classes et relations (Mermaid)

Un seul parser partagé, une seule analyse, deux vues.

Dépendances :
    pip install streamlit networkx pyvis
"""

# ══════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════
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
# PAGE CONFIG — doit être le premier appel Streamlit
# ══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Python Code Intelligence",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════
# STYLES GLOBAUX — thème "studio sombre/clair hybride"
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@500;700&family=DM+Sans:wght@400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background: #0e1117;
    color: #e0e0e0;
}
h1 { font-family: 'Syne', sans-serif; font-weight: 700;
     background: linear-gradient(90deg,#58a6ff,#a5d6ff);
     -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
h2, h3 { font-family: 'Syne', sans-serif; font-weight: 500; color: #c9d1d9; }

/* Bouton principal */
.stButton>button {
    background: linear-gradient(135deg,#1f6feb,#388bfd);
    color: #fff; border: none; border-radius: 8px;
    padding: 0.55em 1.5em;
    font-family: 'DM Sans', sans-serif; font-size: 0.9rem;
    cursor: pointer; transition: opacity .2s, transform .1s;
}
.stButton>button:hover  { opacity: .88; }
.stButton>button:active { transform: scale(.98); }

/* Onglets navigation principaux */
div[data-testid="stTabs"] > div > div > button {
    font-family: 'Syne', sans-serif !important;
    font-size: 1rem !important; font-weight: 500 !important;
}

/* Cartes de stats */
.stat-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 10px; padding: 0.9rem 1rem;
    text-align: center;
}
.stat-card .val { font-size: 1.9rem; font-weight: 700;
                  font-family: 'Syne', sans-serif; color: #58a6ff; }
.stat-card .lbl { font-size: 0.7rem; color: #8b949e; margin-top: 3px; }

/* Badges */
.badge { display:inline-block; padding:2px 9px; border-radius:20px;
         font-size:0.72rem; font-weight:600; margin:1px;
         font-family:'JetBrains Mono',monospace; }
.badge-mod   { background:#1a2744; color:#79c0ff; }
.badge-func  { background:#1f4068; color:#58a6ff; }
.badge-class { background:#3b2f0e; color:#e3b341; }
.badge-async { background:#1b2d1b; color:#3fb950; }
.badge-imp   { background:#2d1b2d; color:#d2a8ff; }
.badge-attr  { background:#1e2a1e; color:#7ee787; }

/* Pills UML */
.class-pill { display:inline-block; padding:3px 10px; border-radius:20px;
              font-size:0.73rem; font-weight:500; margin:2px;
              font-family:'JetBrains Mono',monospace; }
.pill-class   { background:#1a2744; color:#79c0ff; }
.pill-method  { background:#2d2506; color:#e3b341; }
.pill-inherit { background:#0d2818; color:#3fb950; }
.pill-async   { background:#2d1020; color:#f778ba; }

/* Légende graph */
.legend-row { display:flex; align-items:center; gap:8px;
              margin:4px 0; font-size:0.8rem; color:#c9d1d9; }
.dot { width:12px; height:12px; border-radius:50%; display:inline-block; }

/* Metric row UML */
.metric-row { display:flex; gap:12px; margin-bottom:1rem; flex-wrap:wrap; }
.metric-card { background:#161b22; border:1px solid #30363d;
               border-radius:10px; padding:0.8rem 1.1rem;
               min-width:100px; text-align:center; }
.metric-card .val { font-size:1.7rem; font-weight:700;
                    font-family:'Syne',sans-serif; color:#58a6ff; }
.metric-card .lbl { font-size:0.7rem; color:#8b949e; margin-top:2px; }

/* Séparateur de section */
.section-title {
    font-family:'Syne',sans-serif; font-size:1.1rem; font-weight:600;
    color:#58a6ff; border-bottom:1px solid #30363d;
    padding-bottom:6px; margin:1.2rem 0 0.8rem;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES  (partagées par les deux vues)
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
# PARSER PARTAGÉ  (étapes 1 → 7)
# ══════════════════════════════════════════════════════════

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__",
    ".tox", "dist", "build", ".mypy_cache",
    ".pytest_cache", "node_modules", ".eggs",
}

def collect_py_files(project_path: str) -> list[Path]:
    root = Path(project_path).resolve()
    if not root.exists():  raise FileNotFoundError(f"Introuvable : {root}")
    if not root.is_dir():  raise NotADirectoryError(f"Pas un dossier : {root}")
    return sorted(
        p for p in root.rglob("*.py")
        if not any(ex in p.parts for ex in EXCLUDE_DIRS)
    )

def read_file(fp: Path) -> str | None:
    try:    return fp.read_text(encoding="utf-8", errors="replace")
    except OSError: return None

def parse_source(src: str, fname: str = "<unknown>") -> ast.Module | None:
    try:    return ast.parse(src, filename=fname)
    except SyntaxError: return None

def extract_imports(tree: ast.Module) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: out.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            m = node.module or ""
            for a in node.names: out.append(f"{m}.{a.name}")
    return out

def _resolve_name(node) -> Optional[str]:
    if isinstance(node, ast.Name):      return node.id
    if isinstance(node, ast.Attribute): return f"{_resolve_name(node.value)}.{node.attr}"
    return None

def _get_calls(fn) -> list[str]:
    calls = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            n = _resolve_name(node.func)
            if n and n not in calls: calls.append(n)
    return calls

def _get_arg_annotations(node) -> dict[str, str]:
    out = {}
    for arg in node.args.args:
        if arg.annotation:
            try: out[arg.arg] = ast.unparse(arg.annotation)
            except Exception: pass
    return out

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
    return [
        _build_func(n) for n in ast.iter_child_nodes(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

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
            methods=[
                _build_func(c) for c in ast.iter_child_nodes(node)
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
            ], node=node,
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
                            try: tp = ast.unparse(stmt.annotation)
                            except Exception: tp = "Any"
                            attrs.append((nm, tp)); seen.add(nm)
                elif isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if (isinstance(t, ast.Attribute) and
                                isinstance(t.value, ast.Name) and
                                t.value.id == "self" and t.attr not in seen):
                            attrs.append((t.attr, "")); seen.add(t.attr)
    return attrs

def parse_one_file(fp: Path, root: Path) -> ModuleInfo | None:
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
    """Parser avec cache — re-analysé seulement si le chemin change."""
    root  = Path(project_path).resolve()
    files = collect_py_files(project_path)
    out   = []
    for fp in files:
        m = parse_one_file(fp, root)
        if m: out.append(m)
    return out


# ══════════════════════════════════════════════════════════
# VUE ①  —  GRAPHE D'EXÉCUTION  (PyVis / NetworkX)
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
                idx[f"{c.name}.{mt.name}"] = mid
                idx[mt.name] = mid
                if mode in ("contains","both"): G.add_edge(cid, mid, kind="contains")
    if mode in ("calls","both"):
        for m in modules:
            all_fns = list(m.functions) + [mt for c in m.classes for mt in c.methods]
            for f in all_fns:
                src = idx.get(f.name) or f"{m.module_name}.{f.name}"
                for called in f.calls:
                    tgt = idx.get(called) or idx.get(called.split(".")[-1])
                    if tgt and tgt != src: G.add_edge(src, tgt, kind="calls")
    return G

def build_pyvis_html(G: nx.DiGraph, height: int = 700) -> str:
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:#f78166;padding:1rem'>⚠️ Installez pyvis : <code>pip install pyvis</code></p>"
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
        if data.get("docstring"): lines.append(f"📝 {data['docstring'][:80]}…")
        if data.get("bases"):     lines.append(f"Hérite : {', '.join(data['bases'])}")
        if data.get("imports"):   lines.append(f"Imports : {', '.join(data['imports'])}")
        net.add_node(nid, label=label,
                     color=COLOR_MAP.get(kind,"#8b949e"),
                     size=SIZE_MAP.get(kind,15),
                     title="<br>".join(lines),
                     font={"size":11,"color":"#c9d1d9"},
                     borderWidth=2, borderWidthSelected=4)
    edge_clr = {"contains":"#30363d","calls":"#f78166"}
    for src, dst, data in G.edges(data=True):
        k = data.get("kind","calls")
        net.add_edge(src, dst, color=edge_clr.get(k,"#8b949e"),
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


def render_graph_tab(modules: list[ModuleInfo]):
    """Contenu complet de l'onglet Graphe d'exécution."""

    # ── Options dans la sidebar (section graphe) ──────────
    with st.sidebar:
        st.markdown('<div class="section-title">🕸️ Graphe</div>', unsafe_allow_html=True)
        graph_mode = st.selectbox(
            "Type d'arêtes",
            ["both","calls","contains"],
            format_func=lambda x: {
                "both":     "🔗 Appels + Containment",
                "calls":    "📞 Appels uniquement",
                "contains": "📦 Containment uniquement",
            }[x],
            key="graph_mode",
        )
        graph_height   = st.slider("Hauteur (px)", 400, 1000, 680, 50, key="graph_h")
        filter_iso     = st.checkbox("Masquer nœuds isolés", value=False, key="graph_iso")
        max_nodes      = st.slider("Max nœuds", 20, 500, 200, 10, key="graph_max")

        st.markdown('<div class="section-title">🎨 Légende</div>', unsafe_allow_html=True)
        for color, lbl in [("#58a6ff","Module"),("#e3b341","Classe"),
                           ("#3fb950","Fonction"),("#a5d6ff","Méthode")]:
            st.markdown(
                f'<div class="legend-row"><span class="dot" style="background:{color}"></span>{lbl}</div>',
                unsafe_allow_html=True)
        st.markdown(
            '<div class="legend-row"><span style="color:#f78166;font-size:1.1rem">→</span> Appel</div>'
            '<div class="legend-row"><span style="color:#444;font-size:1.1rem">⇢</span> Containment</div>',
            unsafe_allow_html=True)

    # ── Corps ─────────────────────────────────────────────
    G = build_call_graph(modules, mode=graph_mode)
    if filter_iso:
        G.remove_nodes_from(list(nx.isolates(G)))
    if len(G.nodes) > max_nodes:
        top = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)[:max_nodes]
        G   = G.subgraph(top).copy()
        st.info(f"ℹ️ Limité aux {max_nodes} nœuds les plus connectés.")

    st.markdown(
        f"<p style='color:#8b949e;font-size:0.85rem'>"
        f"<b style='color:#c9d1d9'>{G.number_of_nodes()}</b> nœuds · "
        f"<b style='color:#c9d1d9'>{G.number_of_edges()}</b> arêtes</p>",
        unsafe_allow_html=True)

    html_graph = build_pyvis_html(G, height=graph_height)
    components.html(html_graph, height=graph_height + 30, scrolling=False)

    st.divider()
    st.markdown("### 📋 Détail des modules")
    for m in modules:
        with st.expander(f"📄 `{m.module_name}`"):
            if m.docstring:
                st.markdown(f"> {m.docstring}")
            if m.imports:
                badges = " ".join(
                    f'<span class="badge badge-imp">{i.split(".")[-1]}</span>'
                    for i in m.imports[:12])
                st.markdown(f"**Imports** : {badges}", unsafe_allow_html=True)
            if m.functions:
                st.markdown("**Fonctions top-level :**")
                for f in m.functions:
                    ab = '<span class="badge badge-async">async</span>' if f.is_async else ""
                    doc = textwrap.shorten(f.docstring or "–", 80)
                    calls_s = ", ".join(f.calls[:5]) or "–"
                    st.markdown(
                        f'<span class="badge badge-func">{f.name}</span> {ab} '
                        f'`L{f.lineno}` args=`{f.args}`<br>'
                        f'<small>📝 {doc}</small><br>'
                        f'<small>📞 appelle : {calls_s}</small>',
                        unsafe_allow_html=True)
            for c in m.classes:
                st.markdown(
                    f'<span class="badge badge-class">class {c.name}</span> '
                    f'`L{c.lineno}` bases=`{c.bases}`',
                    unsafe_allow_html=True)
                for mt in c.methods:
                    ab = '<span class="badge badge-async">async</span>' if mt.is_async else ""
                    st.markdown(
                        f'&nbsp;&nbsp;↳ <span class="badge badge-func">{mt.name}</span> {ab} `L{mt.lineno}`',
                        unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# VUE ②  —  DIAGRAMMES UML  (Mermaid)
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

def render_mermaid(code: str, height: int = 600, theme: str = "dark") -> None:
    escaped = html_lib.escape(code, quote=False)
    components.html(MERMAID_TPL.format(mermaid_code=escaped, theme=theme),
                    height=height, scrolling=True)

def _san(name: str) -> str:
    return name.replace(".",  "_").replace("-","_").replace("<","").replace(">","")

def _vis(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"): return "-"
    if name.startswith("_"): return "#"
    return "+"

def _fmt(t: str) -> str:
    if not t: return ""
    for k, v in {"Optional[":"?","list[":"list~","dict[":"dict~",
                 "tuple[":"tuple~","set[":"set~"}.items():
        t = t.replace(k, v)
    if "~" in t: t = t.replace("]","~")
    return t[:28]

def gen_mermaid_module(m: ModuleInfo, *, attrs=True, methods=True,
                       private=False, inherit=True) -> str:
    if not m.classes: return ""
    cnames = {c.name for c in m.classes}
    lines  = ["classDiagram"]
    for cls in m.classes:
        cn = _san(cls.name); lines.append(f"    class {cn} {{")
        if "ABC" in cls.bases or "abc.ABC" in cls.bases:
            lines.append("        <<abstract>>")
        elif cls.decorators and "dataclass" in " ".join(cls.decorators):
            lines.append("        <<dataclass>>")
        elif "Protocol" in cls.bases:
            lines.append("        <<interface>>")
        if attrs and cls.node:
            for an, at in extract_attributes(cls.node):
                if not private and an.startswith("_"): continue
                ts = f" {_fmt(at)}" if at else ""
                lines.append(f"        {_vis(an)}{an}{ts}")
        if methods:
            for mt in cls.methods:
                if not private and mt.name.startswith("_") and \
                   mt.name not in ("__init__","__str__","__repr__"): continue
                vis  = _vis(mt.name)
                args = ", ".join(a for a in mt.args if a != "self")[:40]
                ret  = ""
                if mt.node and mt.node.returns:
                    try: ret = f" {_fmt(ast.unparse(mt.node.returns))}"
                    except Exception: pass
                ap = "async " if mt.is_async else ""
                lines.append(f"        {vis}{ap}{mt.name}({args}){ret}")
        lines.append("    }")
    if inherit:
        for cls in m.classes:
            cn = _san(cls.name)
            for b in cls.bases:
                bc = _san(b)
                if b in cnames: lines.append(f"    {bc} <|-- {cn}")
                elif b not in ("object","ABC","abc.ABC",""):
                    lines.append(f"    {bc} <|-- {cn} : extends")
    if attrs:
        for cls in m.classes:
            if not cls.node: continue
            cn = _san(cls.name)
            for an, at in extract_attributes(cls.node):
                for oc in m.classes:
                    if oc.name != cls.name and oc.name in at:
                        lines.append(f"    {cn} --> {_san(oc.name)} : {an}"); break
    return "\n".join(lines)

def gen_mermaid_global(modules: list[ModuleInfo], selected: list[str] | None = None,
                       *, attrs=True, methods=True, private=False, cross=True) -> str:
    filtered = [m for m in modules if selected is None or m.module_name in selected]
    gcls: dict[str,str] = {c.name: m.module_name
                           for m in filtered for c in m.classes}
    lines = ["classDiagram"]
    for m in filtered:
        if not m.classes: continue
        ns = _san(m.module_name.split(".")[-1])
        lines.append(f"    namespace {ns} {{")
        for cls in m.classes:
            cn = _san(cls.name); lines.append(f"        class {cn} {{")
            if "ABC" in cls.bases or "abc.ABC" in cls.bases:
                lines.append("            <<abstract>>")
            elif cls.decorators and "dataclass" in " ".join(cls.decorators):
                lines.append("            <<dataclass>>")
            elif "Protocol" in cls.bases:
                lines.append("            <<interface>>")
            if attrs and cls.node:
                for an, at in extract_attributes(cls.node)[:5]:
                    if not private and an.startswith("_"): continue
                    ts = f" {_fmt(at)}" if at else ""
                    lines.append(f"            {_vis(an)}{an}{ts}")
            if methods:
                for mt in cls.methods[:7]:
                    if not private and mt.name.startswith("_") and mt.name != "__init__": continue
                    args = ", ".join(a for a in mt.args if a != "self")[:30]
                    lines.append(f"            {_vis(mt.name)}{mt.name}({args})")
            lines.append("        }")
        lines.append("    }")
    if cross:
        for m in filtered:
            for cls in m.classes:
                cn = _san(cls.name)
                for b in cls.bases:
                    if b in gcls and b != cls.name:
                        lines.append(f"    {_san(b)} <|-- {cn}")
    return "\n".join(lines)

def mermaid_live_url(code: str, theme: str) -> str:
    state  = json.dumps({"code": code, "mermaid": {"theme": theme}})
    enc    = base64.urlsafe_b64encode(zlib.compress(state.encode(), 9)).decode()
    return f"https://mermaid.live/edit#pako:{enc}"


def render_uml_tab(modules: list[ModuleInfo]):
    """Contenu complet de l'onglet UML."""

    mwc = [m for m in modules if m.classes]
    all_classes = [c for m in modules for c in m.classes]
    all_methods = [mt for c in all_classes for mt in c.methods]

    # ── Options sidebar (section UML) ──────────────────────
    with st.sidebar:
        st.markdown('<div class="section-title">📐 UML</div>', unsafe_allow_html=True)
        show_attrs   = st.checkbox("Attributs",           value=True,  key="uml_attrs")
        show_meths   = st.checkbox("Méthodes",            value=True,  key="uml_meths")
        show_priv    = st.checkbox("Membres privés (_)",  value=False, key="uml_priv")
        show_inh     = st.checkbox("Héritage",            value=True,  key="uml_inh")
        show_cross   = st.checkbox("Relations inter-mod", value=True,  key="uml_cross")
        uml_theme    = st.selectbox("Thème Mermaid",
                                    ["dark","default","forest","neutral","base"],
                                    key="uml_theme")
        uml_h        = st.slider("Hauteur UML (px)", 300, 1200, 580, 50, key="uml_h")
        uml_granul   = st.radio("Granularité",
                                ["Par module","Vue globale"],
                                key="uml_gran")
        st.markdown('<div class="section-title">📖 Notation</div>', unsafe_allow_html=True)
        st.markdown("`+` public &nbsp;`#` protégé &nbsp;`-` privé  \n"
                    "`<|--` héritage &nbsp;`-->` association  \n"
                    "`<<abstract>>` `<<dataclass>>` `<<interface>>`")

    # ── Statistiques ───────────────────────────────────────
    nb_abs = sum(1 for c in all_classes if any(b in ("ABC","abc.ABC") for b in c.bases))
    st.markdown(
        f'<div class="metric-row">'
        f'<div class="metric-card"><div class="val">{len(modules)}</div><div class="lbl">Modules</div></div>'
        f'<div class="metric-card"><div class="val">{len(mwc)}</div><div class="lbl">Avec classes</div></div>'
        f'<div class="metric-card"><div class="val">{len(all_classes)}</div><div class="lbl">Classes</div></div>'
        f'<div class="metric-card"><div class="val">{len(all_methods)}</div><div class="lbl">Méthodes</div></div>'
        f'<div class="metric-card"><div class="val">{nb_abs}</div><div class="lbl">Abstraites</div></div>'
        f'</div>',
        unsafe_allow_html=True)

    if not mwc:
        st.warning("Aucun module ne contient de classes.")
        return

    # ── Mode : vue globale ─────────────────────────────────
    if uml_granul == "Vue globale":
        st.markdown("#### 🌐 Diagramme global multi-modules")
        opts     = [m.module_name for m in mwc]
        selected = st.multiselect("Modules à inclure", opts,
                                  default=opts[:8], key="uml_sel_global")
        if not selected:
            st.info("Sélectionnez au moins un module.")
            return
        code = gen_mermaid_global(modules, selected,
                                  attrs=show_attrs, methods=show_meths,
                                  private=show_priv, cross=show_cross)
        if code.strip() == "classDiagram":
            st.warning("Aucune classe dans la sélection.")
            return
        t1, t2 = st.tabs(["📊 Diagramme", "💻 Code Mermaid"])
        with t1: render_mermaid(code, height=uml_h, theme=uml_theme)
        with t2:
            st.code(code, language="text")
            col1, col2 = st.columns([1,3])
            with col1:
                st.download_button("⬇️ .mmd", data=code,
                                   file_name="uml_global.mmd", mime="text/plain")
            with col2:
                st.markdown(f'<a href="{mermaid_live_url(code, uml_theme)}" target="_blank" '
                            f'style="font-size:.85rem;color:#58a6ff">🔗 Mermaid Live Editor</a>',
                            unsafe_allow_html=True)

    # ── Mode : par module ──────────────────────────────────
    else:
        names = [m.module_name for m in mwc]
        sel   = st.selectbox("Choisir un module",
                             names, format_func=lambda n: f"📄 {n}",
                             key="uml_sel_mod")
        mod   = next((m for m in mwc if m.module_name == sel), None)
        if not mod: return

        # Pills des classes
        pills = ""
        for cls in mod.classes:
            pills += f'<span class="class-pill pill-class">{cls.name}</span>'
            for b in cls.bases:
                if b not in ("object",""):
                    pills += f'<span class="class-pill pill-inherit">⇑ {b}</span>'
            for mt in cls.methods:
                if mt.name == "__init__": continue
                if not show_priv and mt.name.startswith("_"): continue
                p = "pill-async" if mt.is_async else "pill-method"
                pills += f'<span class="class-pill {p}">{mt.name}()</span>'
        st.markdown(pills, unsafe_allow_html=True)
        st.markdown("")

        code = gen_mermaid_module(mod,
                                  attrs=show_attrs, methods=show_meths,
                                  private=show_priv, inherit=show_inh)
        if not code or code.strip() == "classDiagram":
            st.warning("Ce module ne contient aucune classe.")
            return

        t1, t2, t3 = st.tabs(["📊 Diagramme","💻 Code Mermaid","🔍 Détail"])
        with t1: render_mermaid(code, height=uml_h, theme=uml_theme)
        with t2:
            st.code(code, language="text")
            col1, col2 = st.columns([1,3])
            with col1:
                fname = sel.replace(".",  "_")
                st.download_button("⬇️ .mmd", data=code,
                                   file_name=f"uml_{fname}.mmd", mime="text/plain")
            with col2:
                st.markdown(f'<a href="{mermaid_live_url(code, uml_theme)}" target="_blank" '
                            f'style="font-size:.85rem;color:#58a6ff">🔗 Mermaid Live Editor</a>',
                            unsafe_allow_html=True)
        with t3:
            for cls in mod.classes:
                with st.expander(f"🏛️ `{cls.name}`", expanded=False):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**Lignes** `{cls.lineno}–{cls.end_lineno}`")
                        if cls.bases:
                            st.markdown(f"**Hérite** `{', '.join(cls.bases)}`")
                        if cls.decorators:
                            st.markdown(f"**Décorateurs** `{', '.join(cls.decorators)}`")
                        if cls.docstring:
                            st.info(cls.docstring)
                    with c2:
                        st.markdown(f"**{len(cls.methods)} méthodes**")
                        for mt in cls.methods:
                            icon = "⚡" if mt.is_async else "◆"
                            args = ", ".join(a for a in mt.args if a != "self")
                            doc  = textwrap.shorten(mt.docstring or "–", 55)
                            st.markdown(
                                f"{icon} `{mt.name}({args})` L{mt.lineno}  \n"
                                f"<small style='color:#8b949e'>{doc}</small>",
                                unsafe_allow_html=True)

        st.divider()
        st.markdown("#### 📋 Tous les modules avec classes")
        cols = st.columns(3)
        for i, m in enumerate(mwc):
            with cols[i % 3]:
                cls_list = ", ".join(f"`{c.name}`" for c in m.classes)
                st.markdown(
                    f"**{m.module_name.split('.')[-1]}**  \n"
                    f"<small style='color:#8b949e'>{m.module_name}</small>  \n"
                    f"{cls_list}",
                    unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# DASHBOARD  —  STATISTIQUES GLOBALES
# ══════════════════════════════════════════════════════════

def render_overview_tab(modules: list[ModuleInfo]):
    """Onglet récapitulatif : métriques + résumé par module."""
    all_cls  = [c for m in modules for c in m.classes]
    all_fns  = [f for m in modules for f in m.functions]
    all_mts  = [mt for c in all_cls for mt in c.methods]
    no_doc_f = sum(1 for f in all_fns if not f.docstring)
    no_doc_m = sum(1 for mt in all_mts if not mt.docstring)
    nb_async = sum(1 for f in all_fns + all_mts if f.is_async)

    st.markdown("#### 📊 Vue d'ensemble du projet")
    cols = st.columns(7)
    metrics = [
        (len(modules),       "Modules"),
        (len(all_cls),       "Classes"),
        (len(all_fns),       "Fonctions"),
        (len(all_mts),       "Méthodes"),
        (nb_async,           "Async"),
        (no_doc_f + no_doc_m,"Sans docstring"),
        (sum(len(m.imports) for m in modules),"Imports totaux"),
    ]
    for col, (val, lbl) in zip(cols, metrics):
        col.markdown(
            f'<div class="stat-card"><div class="val">{val}</div>'
            f'<div class="lbl">{lbl}</div></div>',
            unsafe_allow_html=True)

    st.divider()

    # Top modules par nombre de fonctions / classes
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Top modules par classes**")
        for m in sorted(modules, key=lambda x: len(x.classes), reverse=True)[:8]:
            bar_w = max(4, int(len(m.classes) / max(len(all_cls),1) * 200))
            st.markdown(
                f'<div style="margin:4px 0">'
                f'<span style="font-family:JetBrains Mono;font-size:.8rem;color:#c9d1d9">'
                f'{m.module_name.split(".")[-1]}</span> '
                f'<span style="display:inline-block;height:10px;width:{bar_w}px;'
                f'background:#e3b341;border-radius:3px;vertical-align:middle"></span> '
                f'<span style="color:#8b949e;font-size:.75rem">{len(m.classes)}</span>'
                f'</div>', unsafe_allow_html=True)
    with col2:
        st.markdown("**Top modules par fonctions**")
        for m in sorted(modules, key=lambda x: len(x.functions), reverse=True)[:8]:
            bar_w = max(4, int(len(m.functions) / max(len(all_fns),1) * 200))
            st.markdown(
                f'<div style="margin:4px 0">'
                f'<span style="font-family:JetBrains Mono;font-size:.8rem;color:#c9d1d9">'
                f'{m.module_name.split(".")[-1]}</span> '
                f'<span style="display:inline-block;height:10px;width:{bar_w}px;'
                f'background:#3fb950;border-radius:3px;vertical-align:middle"></span> '
                f'<span style="color:#8b949e;font-size:.75rem">{len(m.functions)}</span>'
                f'</div>', unsafe_allow_html=True)

    st.divider()

    # Modules sans docstrings
    ndoc = [(m.module_name, f) for m in modules for f in m.functions if not f.docstring]
    if ndoc:
        st.markdown(f"**⚠️ {len(ndoc)} fonctions sans docstring**")
        with st.expander("Voir la liste"):
            for mn, f in ndoc[:40]:
                st.markdown(
                    f'`{mn}` → <span class="badge badge-func">{f.name}</span> L{f.lineno}',
                    unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ══════════════════════════════════════════════════════════

# ── En-tête ───────────────────────────────────────────────
st.markdown("# 🔬 Python Code Intelligence")
st.markdown(
    "<p style='color:#8b949e;margin-top:-10px;font-size:0.95rem'>"
    "Analyse statique · Graphe d'exécution · Diagrammes UML</p>",
    unsafe_allow_html=True)

# ── Sidebar : saisie du chemin + bouton ───────────────────
with st.sidebar:
    st.markdown("## 📂 Projet")
    project_path = st.text_input(
        "Chemin du projet",
        value=".",
        help="Chemin absolu ou relatif vers le dossier racine",
        key="project_path",
    )
    run = st.button("🚀 Analyser le projet", use_container_width=True)
    st.markdown("---")
    st.markdown(
        "<small style='color:#8b949e'>Dépendances :<br>"
        "<code>pip install streamlit networkx pyvis</code></small>",
        unsafe_allow_html=True)

# ── Analyse (avec cache) ──────────────────────────────────
if run or "modules" in st.session_state:
    if run:
        with st.spinner("Analyse en cours…"):
            try:
                st.session_state["modules"] = parse_project(project_path)
                st.session_state["path_ok"] = project_path
            except (FileNotFoundError, NotADirectoryError) as e:
                st.error(f"❌ {e}")
                st.stop()

    modules: list[ModuleInfo] = st.session_state.get("modules", [])
    if not modules:
        st.warning("Aucun fichier Python analysable trouvé.")
        st.stop()

    # ── Navigation par onglets ────────────────────────────
    tab_overview, tab_graph, tab_uml = st.tabs([
        "📊 Vue d'ensemble",
        "🕸️ Graphe d'exécution",
        "📐 Diagrammes UML",
    ])

    with tab_overview:
        render_overview_tab(modules)

    with tab_graph:
        render_graph_tab(modules)

    with tab_uml:
        render_uml_tab(modules)

else:
    # ── Écran d'accueil ───────────────────────────────────
    st.markdown("""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;
                padding:2.5rem 3rem;max-width:620px;margin:3rem auto;text-align:center">
        <div style="font-size:3.5rem">🔬</div>
        <h2 style="color:#58a6ff;font-family:'Syne',sans-serif;margin:.5rem 0">
            Python Code Intelligence</h2>
        <p style="color:#8b949e;font-size:.95rem;line-height:1.7">
            Explorez n'importe quel projet Python en deux visions complémentaires.
        </p>
        <div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin:1.5rem 0">
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:140px">
                <div style="font-size:1.8rem">🕸️</div>
                <div style="color:#58a6ff;font-weight:600;font-size:.9rem;margin:.3rem 0">
                    Graphe d'exécution</div>
                <div style="color:#8b949e;font-size:.78rem">Appels, containment,<br>nœuds interactifs</div>
            </div>
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;
                        padding:.9rem 1.2rem;min-width:140px">
                <div style="font-size:1.8rem">📐</div>
                <div style="color:#e3b341;font-weight:600;font-size:.9rem;margin:.3rem 0">
                    Diagrammes UML</div>
                <div style="color:#8b949e;font-size:.78rem">Classes, héritage,<br>attributs typés</div>
            </div>
        </div>
        <hr style="border:none;border-top:1px solid #30363d;margin:1.2rem 0">
        <p style="color:#8b949e;font-size:.78rem;margin:0">
            Entrez un chemin dans la sidebar et cliquez <b style="color:#c9d1d9">🚀 Analyser</b>
        </p>
    </div>
    """, unsafe_allow_html=True)
