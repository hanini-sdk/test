#!/usr/bin/env python
"""
main.py - Script principal
==========================

Analyse un projet Python et génère la documentation avec LLM.
"""

import sys
from pathlib import Path

from parser import Parser
from graph import Graph
from llm.documenter import LLMDocumenter


def main(project_path: str = "."):
    """
    Analyse un projet Python et génère la documentation.
    
    Args:
        project_path: Chemin vers le projet
    """
    
    print("="*70)
    print("  PYTHON ANALYZER + LLM DOCUMENTATION")
    print("="*70)
    
    # ═══════════════════════════════════════════════════════
    # ÉTAPE 1 : PARSING
    # ═══════════════════════════════════════════════════════
    
    print("\n📖 ÉTAPE 1/3 : PARSING DU PROJET")
    print("-"*70)
    
    try:
        parser = Parser(project_path)
        parser.parse()
        
        stats = parser.get_statistics()
        print(f"\n✅ Parsing terminé")
        print(f"   Modules   : {stats['modules']}")
        print(f"   Classes   : {stats['classes']}")
        print(f"   Fonctions : {stats['functions']}")
        print(f"   Méthodes  : {stats['methods']}")
    except Exception as e:
        print(f"❌ Erreur : {e}")
        return 1
    
    # ═══════════════════════════════════════════════════════
    # ÉTAPE 2 : CONSTRUCTION DU GRAPHE
    # ═══════════════════════════════════════════════════════
    
    print("\n🔗 ÉTAPE 2/3 : CONSTRUCTION DU GRAPHE")
    print("-"*70)
    
    try:
        graph = Graph(parser)
        graph.build()
        
        graph_stats = graph.get_statistics()
        print(f"\n✅ Graphe construit")
        print(f"   Nœuds     : {graph_stats['nodes']}")
        print(f"   Arêtes    : {graph_stats['edges']}")
    except Exception as e:
        print(f"❌ Erreur : {e}")
        return 1
    
    # ═══════════════════════════════════════════════════════
    # ÉTAPE 3 : DOCUMENTATION LLM
    # ═══════════════════════════════════════════════════════
    
    print("\n🤖 ÉTAPE 3/3 : GÉNÉRATION DE LA DOCUMENTATION")
    print("-"*70)
    
    try:
        documenter = LLMDocumenter()
        results = documenter.document_project(graph, parser)
        
        print("\n" + "="*70)
        print("  ✅ DOCUMENTATION GÉNÉRÉE AVEC SUCCÈS")
        print("="*70)
        print(f"\n📁 Fichiers générés :")
        print(f"   Architecture : {results['architecture']}")
        print(f"                  (avec features + workflow)")
        #print(f"   Classes      : {len(results['classes'])} fichiers")
        print("\n💡 Consultez outputs/docs/ pour voir la documentation")
    
    except ValueError as e:
        print(f"\n❌ Configuration manquante : {e}")
        print("\n💡 Pour utiliser le module LLM :")
        print("   1. Obtenez une clé API Gemini : https://makersuite.google.com/app/apikey")
        print("   2. Exportez-la : export GEMINI_API_KEY='votre_clé'")
        print("   OU créez un .env avec : GEMINI_API_KEY=votre_clé")
        return 1
    
    except Exception as e:
        print(f"❌ Erreur : {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n" + "="*70)
    return 0


if __name__ == "__main__":
    project_path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    try:
        exit_code = main(project_path)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrompu par l'utilisateur")
        sys.exit(1)