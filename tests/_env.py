"""Ambiente determinístico para os testes (importado por cada módulo)."""
import os

os.environ["LANGUAGE"] = "pt_BR"
os.environ["LC_ALL"] = "C.UTF-8"
os.environ["GSETTINGS_BACKEND"] = "memory"
