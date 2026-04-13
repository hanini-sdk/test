"""
graph.py - Construction du graphe des relations
===============================================

Ce fichier construit un graphe des relations entre les fichiers Python,
en se concentrant sur les imports de classes entre fichiers.
"""

import networkx as nx
from collections import defaultdict
from parser import Parser, ModuleInfo


# ═══════════════════════════════════════════════════════════
# CLASSE GRAPH
# ═══════════════════════════════════════════════════════════

class Graph:
    """
    Construit un graphe des relations d'imports entre fichiers Python.
    
    Le graphe capture les imports de classes et fonctions d'un fichier à l'autre.
    
    Usage:
        parser = Parser("/path/to/project")
        parser.parse()
        
        graph = Graph(parser)
        graph.build()
        
        G = graph.get_graph()
    """
    
    def __init__(self, parser: Parser):
        """
        Initialise le graphe à partir d'un Parser.
        
        Args:
            parser: Instance de Parser déjà parsée
        """
        self.modules = parser.get_modules()
        self.G = nx.DiGraph()  # Graphe dirigé
        
        # Index : nom_classe → module qui la définit
        self._class_to_module = {}
        
        # Index : nom_fonction → module qui la définit
        self._function_to_module = {}
    
    def build(self):
        """
        Construit le graphe des relations d'imports.
        
        Étapes:
        1. Indexer toutes les classes et fonctions
        2. Créer les nœuds (modules)
        3. Créer les arêtes (imports entre modules)
        """
        print("🔨 Construction du graphe...")
        
        # Étape 1 : Indexer
        self._build_index()
        
        # Étape 2 : Nœuds
        self._build_nodes()
        
        # Étape 3 : Arêtes d'imports
        self._build_import_edges()
        
        print(f"✅ Graphe construit : {self.G.number_of_nodes()} nœuds, "
              f"{self.G.number_of_edges()} arêtes")
    
    def get_graph(self) -> nx.DiGraph:
        """Retourne le graphe NetworkX"""
        return self.G
    
    def get_statistics(self) -> dict:
        """Retourne des statistiques sur le graphe"""
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
            "avg_degree": (
                sum(dict(self.G.degree()).values()) / max(1, self.G.number_of_nodes())
            )
        }
    
    def get_module_dependencies(self, module_name: str) -> dict:
        """
        Retourne les dépendances d'un module.
        
        Args:
            module_name: Nom du module
        
        Returns:
            Dict avec 'imports' (ce qu'il importe) et 'imported_by' (qui l'importe)
        """
        if module_name not in self.G:
            return {"imports": [], "imported_by": []}
        
        return {
            "imports": list(self.G.successors(module_name)),
            "imported_by": list(self.G.predecessors(module_name))
        }
    
    def export_graphml(self, filepath: str):
        """Exporte le graphe au format GraphML"""
        nx.write_graphml(self.G, filepath)
        print(f"📊 Graphe exporté : {filepath}")
    
    # ═══════════════════════════════════════════════════════
    # MÉTHODES PRIVÉES
    # ═══════════════════════════════════════════════════════
    
    def _build_index(self):
        """Indexe toutes les classes et fonctions par module"""
        for module in self.modules:
            # Classes
            for cls in module.classes:
                self._class_to_module[cls.name] = module.module_name
            
            # Fonctions
            for func in module.functions:
                self._function_to_module[func.name] = module.module_name
    
    def _build_nodes(self):
        """Crée les nœuds du graphe (un par module)"""
        for module in self.modules:
            self.G.add_node(
                module.module_name,
                label=module.module_name.split(".")[-1],
                num_classes=len(module.classes),
                num_functions=len(module.functions),
                filepath=module.filepath
            )
    
    def _build_import_edges(self):
        """
        Crée les arêtes du graphe (imports entre modules).
        
        Une arête A → B signifie : "A importe quelque chose de B"
        """
        for module in self.modules:
            module_name = module.module_name
            
            for imp in module.imports:
                # Vérifier si l'import vient d'un module du projet
                target_module = None
                
                # Cas 1 : Import d'un module complet
                # Ex: import auth.user
                if imp.module == imp.name and imp.module in self.G:
                    target_module = imp.module
                
                # Cas 2 : Import d'une classe depuis un module
                # Ex: from auth.user import User
                elif imp.name in self._class_to_module:
                    target_module = self._class_to_module[imp.name]
                
                # Cas 3 : Import d'une fonction depuis un module
                # Ex: from utils import helper_function
                elif imp.name in self._function_to_module:
                    target_module = self._function_to_module[imp.name]
                
                # Créer l'arête si on a trouvé le module cible
                if target_module and target_module != module_name:
                    # Éviter les auto-références
                    if not self.G.has_edge(module_name, target_module):
                        self.G.add_edge(
                            module_name,
                            target_module,
                            imports=[imp.name]
                        )
                    else:
                        # Ajouter l'import à la liste
                        self.G[module_name][target_module]['imports'].append(imp.name)


# ═══════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from parser import Parser
    
    project_path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    # Parser
    parser = Parser(project_path)
    parser.parse()
    
    # Graphe
    graph = Graph(parser)
    graph.build()
    
    # Statistiques
    stats = graph.get_statistics()
    print("\n" + "="*50)
    print("📊 STATISTIQUES DU GRAPHE")
    print("="*50)
    print(f"Nœuds (modules) : {stats['nodes']}")
    print(f"Arêtes (imports): {stats['edges']}")
    print(f"Degré moyen     : {stats['avg_degree']:.2f}")
    print("="*50)
    
    # Exemples de dépendances
    G = graph.get_graph()
    if G.number_of_nodes() > 0:
        print("\n📦 EXEMPLES DE DÉPENDANCES:")
        for i, (source, target, data) in enumerate(G.edges(data=True)):
            if i >= 5:
                print(f"... et {G.number_of_edges() - 5} autres")
                break
            imports = data.get('imports', [])
            print(f"  {source} → {target}")
            print(f"    Importe: {', '.join(imports[:3])}")