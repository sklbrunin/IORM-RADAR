"""Faz os testes enxergarem os módulos do projeto (coleta/, processamento/)
não importa de qual pasta o pytest for executado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
