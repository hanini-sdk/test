"""
llm/documenter.py - Documentation intelligente multi-niveaux
============================================================

Génère automatiquement de la documentation à plusieurs niveaux :
- Vue d'ensemble architecturale
- Documentation par module
- Documentation par classe
"""

import time
from pathlib import Path
import google.generativeai as genai

from .config import GeminiConfig


class LLMDocumenter:
    """
    Génère de la documentation intelligente avec Gemini.
    
    Usage:
        documenter = LLMDocumenter()
        documenter.document_project(graph, parser, output_dir="outputs/docs")
    """
    
    def __init__(self, config: GeminiConfig = None):
        """
        Initialise le documenter.
        
        Args:
            config: Configuration Gemini (charge depuis env si None)
        """
        self.config = config or GeminiConfig.from_env()
        
        # Configurer Gemini
        genai.configure(api_key=self.config.api_key)
        
        # Créer le modèle
        self.model = genai.GenerativeModel(
            self.config.model,
            generation_config={
                "temperature": self.config.temperature,
                "max_output_tokens": self.config.max_output_tokens,
            }
        )
        
        # Statistiques
        self.stats = {
            "total_calls": 0,
            "errors": 0,
        }
    
    def document_project(self, graph, parser, output_dir: str = "outputs/docs"):
        """
        Génère la documentation complète du projet.
        
        Args:
            graph: Instance de Graph
            parser: Instance de Parser
            output_dir: Dossier de sortie
        
        Returns:
            Dict avec les chemins des fichiers générés
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        print("🤖 Génération de la documentation avec Gemini...")
        results = {}
        
        # 1. Vue d'ensemble architecturale (avec features et workflow)
        print("\n📋 1/2 - Architecture globale + Features + Workflow...")
        overview = self.generate_architecture_overview(graph, parser)
        overview_path = output_path / "ARCHITECTURE.md"
        self._save(overview, overview_path)
        results["architecture"] = overview_path
        
        # 2. Documentation des classes principales
        #print("\n🏛️  2/2 - Documentation des classes...")
        #classes_dir = output_path / "classes"
        #classes_paths = self.generate_classes_documentation(parser, classes_dir, limit=5)
        #results["classes"] = classes_paths
        
        print(f"\n✅ Documentation générée dans : {output_path}")
        print(f"📊 Appels API : {self.stats['total_calls']}")
        
        return results
    
    def generate_architecture_overview(self, graph, parser) -> str:
        """Génère la vue d'ensemble architecturale avec features et workflow"""
        
        G = graph.get_graph()
        stats = parser.get_statistics()
        modules = parser.get_modules()
        
        # Préparer les modules principaux
        modules_list = "\n".join(
            f"- {m.module_name} ({len(m.classes)} classes, {len(m.functions)} fonctions)"
            for m in modules[:10]
        )
        
        # Préparer les dépendances
        dependencies_list = "\n".join(
            f"- {source} → {target} (importe: {', '.join(data['imports'][:3])})"
            for source, target, data in list(G.edges(data=True))[:15]
        )
        
        # Extraire les classes principales
        all_classes = []
        for m in modules:
            for cls in m.classes:
                all_classes.append(f"{m.module_name}.{cls.name}")
        
        classes_list = "\n".join(f"- {cls}" for cls in all_classes[:20])
        
        prompt = f"""Tu es un architecte logiciel expert.

Analyse ce projet Python et génère une documentation d'architecture claire et structurée.

## STATISTIQUES
- Modules: {stats['modules']}
- Classes: {stats['classes']}
- Fonctions: {stats['functions']}
- Méthodes: {stats['methods']}
- Relations d'imports: {G.number_of_edges()}

## MODULES DU PROJET
{modules_list}

## CLASSES PRINCIPALES
{classes_list}

## DÉPENDANCES (imports entre fichiers)
{dependencies_list}

## TÂCHE

Génère une documentation markdown structurée avec EXACTEMENT ces sections :

# Architecture du Projet

## 1. Vue d'ensemble
Décris en 2-3 paragraphes :
- Le type d'application (web app, CLI, librairie, outil d'analyse, etc.)
- L'architecture générale (comment le code est structuré)
- Les technologies principales utilisées

## 2. Features principales

Identifie les **features fonctionnelles** du projet (groupes de fonctionnalités cohérentes).
Une feature peut regrouper un ou plusieurs fichiers Python qui travaillent ensemble.

Pour chaque feature identifiée :

### Feature : [Nom descriptif]
- **Description** : Ce que fait cette feature d'un point de vue utilisateur/métier
- **Fichiers impliqués** : Liste des modules Python qui composent cette feature
- **Rôle** : Responsabilité principale de cette feature dans le projet

Exemples de features :
- Parsing de code Python
- Construction de graphe
- Génération de documentation
- Analyse de données
- Interface utilisateur
- etc.

## 3. Workflow général

Décris le parcours complet de l'input à l'output du projet.

Crée un **diagramme de workflow en Mermaid** qui montre :
- Point d'entrée (input)
- Étapes de traitement
- Flux de données
- Point de sortie (output)

```mermaid
graph TD
    A[Input: ...] --> B[Étape 1: ...]
    B --> C[Étape 2: ...]
    C --> D[Étape 3: ...]
    D --> E[Output: ...]
```

Puis explique le workflow en quelques paragraphes :
- Qu'est-ce qui entre dans le système ?
- Quelles transformations sont appliquées ?
- Qu'est-ce qui sort du système ?

## 4. Modules principaux

Pour les 3-5 modules les plus importants (selon les dépendances) :

### [Nom du module]
- **Rôle** : Responsabilité principale
- **Utilise** : Modules dont il dépend
- **Utilisé par** : Modules qui dépendent de lui
- **Importance** : Pourquoi il est central

Sois précis, technique et basé sur les données fournies."""

        return self._generate(prompt)
    
    def generate_classes_documentation(self, parser, output_dir: Path, limit: int = 5) -> list[Path]:
        """Génère la documentation des classes principales"""
        
        # Collecter toutes les classes
        all_classes = []
        for module in parser.get_modules():
            for cls in module.classes:
                all_classes.append((module, cls))
        
        # Trier par nombre de méthodes
        all_classes.sort(key=lambda x: len(x[1].methods), reverse=True)
        top_classes = all_classes[:limit]
        
        paths = []
        total = len(top_classes)
        
        for i, (module, cls) in enumerate(top_classes, 1):
            print(f"   Classe {i}/{total}: {cls.name}")
            
            doc = self.generate_class_documentation(module, cls)
            
            # Sauvegarder
            safe_name = f"{module.module_name.replace('.', '_')}_{cls.name}"
            path = output_dir / f"{safe_name}.md"
            self._save(doc, path)
            paths.append(path)
        
        return paths
    
    def generate_class_documentation(self, module, cls) -> str:
        """Génère la documentation d'une classe"""
        
        # Extraire le code de la classe
        start = cls.lineno - 1
        end = min(start + 50, len(module.source_lines))
        class_code = "".join(module.source_lines[start:end])
        if end < len(module.source_lines):
            class_code += "\n    # ... (code tronqué)"
        
        prompt = f"""Tu es un expert en conception orientée objet Python.

Documente cette classe Python.

## CLASSE
Nom: {cls.name}
Module: {module.module_name}
Hérite de: {', '.join(cls.bases) if cls.bases else 'object'}

## MÉTHODES ({len(cls.methods)})
{chr(10).join(f'- {m.name}({", ".join(m.args)})' for m in cls.methods[:10])}

## CODE
```python
{class_code}
```

## TÂCHE

Génère une documentation markdown :

# Classe: {cls.name}

## Rôle
(À quoi sert cette classe ?)

## Responsabilités
(Que fait-elle ? Respecte-t-elle le principe de responsabilité unique ?)

## Méthodes principales
(Décris les 3-5 méthodes les plus importantes)

## Usage
(Exemple d'utilisation typique)

Sois technique et précis."""

        return self._generate(prompt)
    
    # ═══════════════════════════════════════════════════════
    # MÉTHODES UTILITAIRES
    # ═══════════════════════════════════════════════════════
    
    def _generate(self, prompt: str, max_retries: int = 3) -> str:
        """
        Génère une réponse avec Gemini.
        
        Args:
            prompt: Le prompt
            max_retries: Nombre de tentatives
        
        Returns:
            La réponse générée
        """
        for attempt in range(max_retries):
            try:
                self.stats["total_calls"] += 1
                
                response = self.model.generate_content(prompt)
                return response.text
            
            except Exception as e:
                self.stats["errors"] += 1
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⚠️  Erreur API (tentative {attempt + 1}/{max_retries}): {e}")
                    print(f"   Nouvelle tentative dans {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Échec après {max_retries} tentatives: {e}")
    
    def _save(self, content: str, filepath: Path):
        """Sauvegarde le contenu"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        print(f"   ✅ Sauvegardé: {filepath.name}")