"""
app.py - Interface Streamlit pour visualiser la documentation
==============================================================

Application web pour explorer la documentation générée avec une
belle visualisation des diagrammes Mermaid.

Usage:
    streamlit run app.py
"""

import streamlit as st
from pathlib import Path
import re


# ═══════════════════════════════════════════════════════════
# CONFIGURATION DE LA PAGE
# ═══════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Python Analyzer - Documentation",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ═══════════════════════════════════════════════════════════
# STYLES CSS PERSONNALISÉS
# ═══════════════════════════════════════════════════════════

st.markdown("""
<style>
    /* Style général */
    .main {
        background-color: #0e1117;
    }
    
    /* Titres */
    h1 {
        color: #58a6ff;
        border-bottom: 2px solid #58a6ff;
        padding-bottom: 10px;
    }
    
    h2 {
        color: #79c0ff;
        margin-top: 30px;
    }
    
    h3 {
        color: #a5d6ff;
    }
    
    /* Code blocks */
    code {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 2px 6px;
        color: #ffa657;
    }
    
    pre {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 16px;
    }
    
    /* Listes */
    ul, ol {
        line-height: 1.8;
    }
    
    li {
        margin: 8px 0;
    }
    
    /* Liens */
    a {
        color: #58a6ff;
        text-decoration: none;
    }
    
    a:hover {
        text-decoration: underline;
    }
    
    /* Citations */
    blockquote {
        border-left: 4px solid #58a6ff;
        padding-left: 16px;
        color: #8b949e;
        font-style: italic;
    }
    
    /* Tableaux */
    table {
        border-collapse: collapse;
        width: 100%;
        margin: 20px 0;
    }
    
    th {
        background-color: #161b22;
        color: #58a6ff;
        padding: 12px;
        text-align: left;
        border: 1px solid #30363d;
    }
    
    td {
        padding: 10px;
        border: 1px solid #30363d;
    }
    
    tr:hover {
        background-color: #161b22;
    }
    
    /* Sidebar */
    .css-1d391kg {
        background-color: #0d1117;
    }
    
    /* Mermaid container */
    .mermaid-container {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 20px;
        margin: 20px 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    /* Feature cards */
    .feature-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 20px;
        margin: 15px 0;
    }
    
    .feature-card h3 {
        margin-top: 0;
        color: #58a6ff;
    }
    
    /* Info box */
    .info-box {
        background-color: #1f2937;
        border-left: 4px solid #58a6ff;
        padding: 16px;
        margin: 16px 0;
        border-radius: 4px;
    }
    
    /* Stats */
    .stat-box {
        background: linear-gradient(135deg, #1f2937 0%, #161b22 100%);
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        margin: 10px;
    }
    
    .stat-value {
        font-size: 2em;
        font-weight: bold;
        color: #58a6ff;
    }
    
    .stat-label {
        color: #8b949e;
        font-size: 0.9em;
        margin-top: 5px;
    }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
# FONCTIONS UTILITAIRES
# ═══════════════════════════════════════════════════════════

def extract_mermaid_diagrams(markdown_text):
    """
    Extrait tous les diagrammes Mermaid du markdown.
    
    Returns:
        Liste de tuples (position, code_mermaid)
    """
    pattern = r'```mermaid\s*\n(.*?)\n```'
    matches = re.finditer(pattern, markdown_text, re.DOTALL)
    
    diagrams = []
    for match in matches:
        diagrams.append({
            'position': match.start(),
            'code': match.group(1).strip()
        })
    
    return diagrams


def replace_mermaid_with_placeholder(markdown_text):
    """
    Remplace les blocs Mermaid par des placeholders.
    
    Returns:
        Texte markdown modifié, liste des codes Mermaid
    """
    diagrams = extract_mermaid_diagrams(markdown_text)
    
    # Remplacer par des placeholders
    modified_text = markdown_text
    for i, diagram in enumerate(diagrams):
        placeholder = f"\n\n**📊 Diagramme Mermaid #{i+1}**\n\n"
        pattern = r'```mermaid\s*\n' + re.escape(diagram['code']) + r'\n```'
        modified_text = re.sub(pattern, placeholder, modified_text, count=1)
    
    return modified_text, diagrams


def render_mermaid(mermaid_code, diagram_id="mermaid-diagram"):
    """
    Rend un diagramme Mermaid avec HTML/JS.
    """
    # Nettoyer le code (retirer les styles non supportés)
    clean_code = mermaid_code.strip()
    
    # Retirer les lignes de style qui peuvent causer des erreurs
    lines = clean_code.split('\n')
    filtered_lines = [
        line for line in lines 
        if not line.strip().startswith('style ')
    ]
    clean_code = '\n'.join(filtered_lines)
    
    # Échapper les caractères spéciaux pour le HTML
    clean_code = clean_code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    html = f"""
    <div class="mermaid-container">
        <div id="{diagram_id}" class="mermaid">
{clean_code}
        </div>
    </div>
    
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        
        mermaid.initialize({{ 
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose',
            themeVariables: {{
                primaryColor: '#58a6ff',
                primaryTextColor: '#0d1117',
                primaryBorderColor: '#30363d',
                lineColor: '#58a6ff',
                secondaryColor: '#1f6feb',
                tertiaryColor: '#f0f6fc',
                background: '#ffffff',
                mainBkg: '#ffffff',
                secondBkg: '#f6f8fa',
                border1: '#d0d7de',
                border2: '#d0d7de',
                fontFamily: 'ui-monospace, monospace'
            }}
        }});
        
        // Gérer les erreurs de rendu
        try {{
            mermaid.run({{
                nodes: document.querySelectorAll('#{diagram_id}')
            }});
        }} catch(err) {{
            console.error('Erreur Mermaid:', err);
            document.getElementById('{diagram_id}').innerHTML = 
                '<p style="color: red; padding: 20px;">Erreur de rendu du diagramme. Voir le code source ci-dessous.</p>';
        }}
    </script>
    """
    
    return html


def parse_markdown_sections(markdown_text):
    """
    Parse le markdown et extrait les sections principales.
    
    Returns:
        Dict avec titre, sections, etc.
    """
    lines = markdown_text.split('\n')
    
    # Trouver le titre principal
    title = "Documentation"
    for line in lines:
        if line.startswith('# '):
            title = line[2:].strip()
            break
    
    # Extraire les sections H2
    sections = []
    current_section = None
    current_content = []
    
    for line in lines:
        if line.startswith('## '):
            # Sauvegarder la section précédente
            if current_section:
                sections.append({
                    'title': current_section,
                    'content': '\n'.join(current_content)
                })
            # Nouvelle section
            current_section = line[3:].strip()
            current_content = []
        else:
            current_content.append(line)
    
    # Dernière section
    if current_section:
        sections.append({
            'title': current_section,
            'content': '\n'.join(current_content)
        })
    
    return {
        'title': title,
        'sections': sections
    }


def extract_statistics(markdown_text):
    """Extrait les statistiques du document si présentes."""
    stats = {}
    
    # Chercher des patterns de stats
    patterns = {
        'modules': r'Modules[:\s]+(\d+)',
        'classes': r'Classes[:\s]+(\d+)',
        'functions': r'Fonctions[:\s]+(\d+)',
        'methods': r'Méthodes[:\s]+(\d+)',
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, markdown_text, re.IGNORECASE)
        if match:
            stats[key] = int(match.group(1))
    
    return stats


# ═══════════════════════════════════════════════════════════
# CHARGEMENT DE LA DOCUMENTATION
# ═══════════════════════════════════════════════════════════

def load_documentation():
    """Charge tous les fichiers de documentation disponibles."""
    docs_path = Path("outputs/docs")
    
    if not docs_path.exists():
        return None
    
    docs = {}
    
    # Architecture
    arch_file = docs_path / "ARCHITECTURE.md"
    if arch_file.exists():
        docs['architecture'] = arch_file.read_text(encoding='utf-8')
    
    # Classes
    classes_dir = docs_path / "classes"
    if classes_dir.exists():
        docs['classes'] = {}
        for class_file in sorted(classes_dir.glob("*.md")):
            class_name = class_file.stem
            docs['classes'][class_name] = class_file.read_text(encoding='utf-8')
    
    return docs


# ═══════════════════════════════════════════════════════════
# INTERFACE PRINCIPALE
# ═══════════════════════════════════════════════════════════

def main():
    """Point d'entrée de l'application Streamlit."""
    
    # En-tête
    st.title("🔬 Python Analyzer - Documentation")
    st.markdown("---")
    
    # Charger la documentation
    docs = load_documentation()
    
    if not docs:
        # Message d'erreur stylisé
        st.error("❌ Aucune documentation trouvée dans `outputs/docs/`")
        
        st.markdown("""
        ### 💡 Pour générer la documentation :
        
        **Étape 1 : Configurer Gemini API**
        ```bash
        export GEMINI_API_KEY="votre_clé_api"
        ```
        Obtenez votre clé sur : [Google AI Studio](https://makersuite.google.com/app/apikey)
        
        **Étape 2 : Générer la documentation**
        ```bash
        python main.py /path/to/votre/projet
        
        # Exemple : analyser le projet courant
        python main.py .
        ```
        
        **Étape 3 : Actualiser cette page**
        Appuyez sur `R` ou rafraîchissez le navigateur
        """)
        
        # Afficher un exemple de ce qui sera généré
        with st.expander("📖 Aperçu de ce qui sera généré"):
            st.markdown("""
            Après avoir généré la documentation, vous verrez :
            
            - **📋 Architecture globale**
              - Vue d'ensemble du projet
              - Features principales détectées automatiquement
              - Diagramme de workflow (Mermaid)
              - Modules principaux et leurs dépendances
            
            - **🏛️ Documentation des classes**
              - Classes principales du projet
              - Rôles et responsabilités
              - Méthodes importantes
              - Exemples d'utilisation
            """)
        
        st.info("🔄 Cette page se mettra à jour automatiquement une fois la documentation générée.")
        return
    
    # Sidebar - Navigation
    st.sidebar.title("📚 Navigation")
    
    # Choix du document
    doc_choice = st.sidebar.radio(
        "Choisir un document",
        ["📋 Architecture globale"] + 
        [f"🏛️ Classe: {name}" for name in docs.get('classes', {}).keys()]
    )
    
    # ═══════════════════════════════════════════════════════
    # AFFICHAGE DE L'ARCHITECTURE
    # ═══════════════════════════════════════════════════════
    
    if doc_choice == "📋 Architecture globale":
        arch_content = docs.get('architecture', '')
        
        if not arch_content:
            st.warning("⚠️ Architecture non disponible")
            return
        
        # Extraire les stats
        stats = extract_statistics(arch_content)
        
        # Afficher les stats en haut
        if stats:
            st.markdown("### 📊 Statistiques du projet")
            cols = st.columns(len(stats))
            for i, (key, value) in enumerate(stats.items()):
                with cols[i]:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="stat-value">{value}</div>
                        <div class="stat-label">{key.capitalize()}</div>
                    </div>
                    """, unsafe_allow_html=True)
            st.markdown("---")
        
        # Parser le markdown
        parsed = parse_markdown_sections(arch_content)
        
        # Titre principal
        st.header(parsed['title'])
        
        # Pour chaque section
        for section in parsed['sections']:
            # Séparer le markdown et les diagrammes Mermaid
            content, diagrams = replace_mermaid_with_placeholder(section['content'])
            
            # Afficher le titre de section
            st.subheader(section['title'])
            
            # Afficher le contenu markdown
            if content.strip():
                st.markdown(content)
            
            # Afficher les diagrammes Mermaid
            for i, diagram in enumerate(diagrams):
                diagram_id = f"mermaid-{section['title'].replace(' ', '-')}-{i}"
                
                # Titre du diagramme
                st.markdown(f"**📊 Diagramme : {section['title']}**")
                
                # Render Mermaid
                mermaid_html = render_mermaid(diagram['code'], diagram_id)
                st.components.v1.html(mermaid_html, height=400, scrolling=True)
                
                # Expander avec le code source
                with st.expander("🔍 Voir le code Mermaid"):
                    st.code(diagram['code'], language='mermaid')
    
    # ═══════════════════════════════════════════════════════
    # AFFICHAGE D'UNE CLASSE
    # ═══════════════════════════════════════════════════════
    
    else:
        # Extraire le nom de la classe
        class_name = doc_choice.split(": ")[1]
        class_content = docs['classes'].get(class_name, '')
        
        if not class_content:
            st.warning(f"⚠️ Documentation de {class_name} non disponible")
            return
        
        # Parser et afficher
        parsed = parse_markdown_sections(class_content)
        
        st.header(parsed['title'])
        
        for section in parsed['sections']:
            content, diagrams = replace_mermaid_with_placeholder(section['content'])
            
            st.subheader(section['title'])
            
            if content.strip():
                st.markdown(content)
            
            for i, diagram in enumerate(diagrams):
                diagram_id = f"mermaid-class-{class_name}-{i}"
                mermaid_html = render_mermaid(diagram['code'], diagram_id)
                st.components.v1.html(mermaid_html, height=400, scrolling=True)
    
    # ═══════════════════════════════════════════════════════
    # FOOTER
    # ═══════════════════════════════════════════════════════
    
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #8b949e; padding: 20px;'>
        Généré par <strong>Python Analyzer</strong> avec ❤️ et Gemini
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
