import os
import sys
from pathlib import Path


def _add_project_root_to_syspath():
    """
    Garante que a raiz do projeto esteja no sys.path para imports do tipo:
      from parsers.cnh import analyze_cnh

    Funciona mesmo se pytest for executado fora da raiz.
    """
    tests_dir = Path(__file__).resolve().parent
    project_root = tests_dir.parent  # .../projeto

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    # Opcional: também exporta PYTHONPATH para subprocessos (se você usar futuramente)
    os.environ.setdefault("PYTHONPATH", root_str)


_add_project_root_to_syspath()
