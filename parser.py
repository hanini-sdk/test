"""
parser.py - Parser de projets Python
=====================================

Ce fichier contient le parser qui analyse un projet Python complet
et extrait toutes les informations via l'AST (Abstract Syntax Tree).
"""

import ast
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ═══════════════════════════════════════════════════════════

@dataclass
class ImportInfo:
    """Information sur un import"""
    module: str              # "auth.user"
    name: str                # "User"
    alias: Optional[str]     # "U" si "import ... as U"


@dataclass
class FunctionInfo:
    """Information sur une fonction"""
    name: str
    lineno: int
    args: list[str]
    docstring: Optional[str]


@dataclass
class ClassInfo:
    """Information sur une classe"""
    name: str
    lineno: int
    bases: list[str]         # Classes parentes
    methods: list[FunctionInfo]
    docstring: Optional[str]


@dataclass
class ModuleInfo:
    """Information sur un module (fichier .py)"""
    filepath: str
    module_name: str         # "package.subpackage.module"
    docstring: Optional[str]
    imports: list[ImportInfo]
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    source_lines: list[str]


# ═══════════════════════════════════════════════════════════
# CLASSE PARSER
# ═══════════════════════════════════════════════════════════

class Parser:
    """
    Parse un projet Python complet et extrait toutes les informations.
    
    Usage:
        parser = Parser("/path/to/project")
        parser.parse()
        modules = parser.get_modules()
    """
    
    # Dossiers à exclure
    EXCLUDE_DIRS = {
        ".git", ".venv", "venv", "env", "__pycache__", 
        ".tox", "dist", "build", ".mypy_cache", ".pytest_cache",
        "node_modules", ".eggs", ".idea", ".vscode"
    }
    
    def __init__(self, project_path: str):
        """
        Initialise le parser.
        
        Args:
            project_path: Chemin vers le projet Python
        """
        self.project_root = Path(project_path).resolve()
        
        if not self.project_root.exists():
            raise FileNotFoundError(f"Projet introuvable : {self.project_root}")
        
        if not self.project_root.is_dir():
            raise NotADirectoryError(f"Pas un dossier : {self.project_root}")
        
        self.modules: list[ModuleInfo] = []
    
    def parse(self):
        """Parse tous les fichiers Python du projet"""
        print(f"🔍 Parsing du projet : {self.project_root}")
        
        # Collecter les fichiers Python
        py_files = [
            p for p in self.project_root.rglob("*.py")
            if not any(excluded in p.parts for excluded in self.EXCLUDE_DIRS)
        ]
        
        print(f"📄 {len(py_files)} fichiers Python trouvés")
        
        # Parser chaque fichier
        for py_file in sorted(py_files):
            module = self._parse_file(py_file)
            if module:
                self.modules.append(module)
        
        print(f"✅ Parsing terminé : {len(self.modules)} modules")
    
    def get_modules(self) -> list[ModuleInfo]:
        """Retourne la liste des modules parsés"""
        return self.modules
    
    def get_statistics(self) -> dict:
        """Retourne des statistiques sur le projet"""
        total_classes = sum(len(m.classes) for m in self.modules)
        total_functions = sum(len(m.functions) for m in self.modules)
        total_methods = sum(
            len(cls.methods) 
            for m in self.modules 
            for cls in m.classes
        )
        total_imports = sum(len(m.imports) for m in self.modules)
        
        return {
            "modules": len(self.modules),
            "classes": total_classes,
            "functions": total_functions,
            "methods": total_methods,
            "imports": total_imports,
        }
    
    # ═══════════════════════════════════════════════════════
    # MÉTHODES PRIVÉES
    # ═══════════════════════════════════════════════════════
    
    def _parse_file(self, filepath: Path) -> Optional[ModuleInfo]:
        """Parse un fichier Python"""
        try:
            # Lire le code source
            source = filepath.read_text(encoding="utf-8", errors="replace")
            
            # Parser avec AST
            tree = ast.parse(source, filename=str(filepath))
            
            # Nom du module
            rel_path = filepath.relative_to(self.project_root)
            module_name = ".".join(rel_path.with_suffix("").parts)
            
            # Extraire les informations
            return ModuleInfo(
                filepath=str(filepath),
                module_name=module_name,
                docstring=ast.get_docstring(tree),
                imports=self._extract_imports(tree),
                functions=self._extract_functions(tree),
                classes=self._extract_classes(tree),
                source_lines=source.splitlines(keepends=True)
            )
        
        except SyntaxError as e:
            print(f"⚠️  Erreur syntaxe dans {filepath}: {e}")
            return None
        except Exception as e:
            print(f"⚠️  Erreur parsing {filepath}: {e}")
            return None
    
    def _extract_imports(self, tree: ast.Module) -> list[ImportInfo]:
        """Extrait les imports"""
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # import foo, bar as b
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=alias.name,
                        name=alias.name,
                        alias=alias.asname
                    ))
            
            elif isinstance(node, ast.ImportFrom):
                # from foo import bar, baz as b
                module = node.module or ""
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=module,
                        name=alias.name,
                        alias=alias.asname
                    ))
        
        return imports
    
    def _extract_functions(self, tree: ast.Module) -> list[FunctionInfo]:
        """Extrait les fonctions top-level"""
        functions = []
        
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(FunctionInfo(
                    name=node.name,
                    lineno=node.lineno,
                    args=[arg.arg for arg in node.args.args],
                    docstring=ast.get_docstring(node)
                ))
        
        return functions
    
    def _extract_classes(self, tree: ast.Module) -> list[ClassInfo]:
        """Extrait les classes"""
        classes = []
        
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                # Extraire les méthodes
                methods = []
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(FunctionInfo(
                            name=child.name,
                            lineno=child.lineno,
                            args=[arg.arg for arg in child.args.args],
                            docstring=ast.get_docstring(child)
                        ))
                
                # Extraire les classes parentes
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(ast.unparse(base))
                
                classes.append(ClassInfo(
                    name=node.name,
                    lineno=node.lineno,
                    bases=bases,
                    methods=methods,
                    docstring=ast.get_docstring(node)
                ))
        
        return classes


# ═══════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    project_path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    parser = Parser(project_path)
    parser.parse()
    
    stats = parser.get_statistics()
    print("\n" + "="*50)
    print("📊 STATISTIQUES")
    print("="*50)
    print(f"Modules   : {stats['modules']}")
    print(f"Classes   : {stats['classes']}")
    print(f"Fonctions : {stats['functions']}")
    print(f"Méthodes  : {stats['methods']}")
    print(f"Imports   : {stats['imports']}")
    print("="*50)