"""Capa A2UI: catalogo, validacion y artefactos derivados.

`catalog.json` es la fuente unica de verdad. De ahi salen:
  * el fragmento del system prompt (scripts/gen_catalog_artifacts.py)
  * el validador de este modulo
  * los tipos TypeScript de web/src/catalog.types.ts

Regla de equipo: nadie agrega un componente sin agregarlo al catalogo primero.
El test de contrato falla si los tres se desalinean.
"""

from a2ui.models import (  # noqa: F401
    CATALOG,
    CATALOG_PATH,
    ValidationResult,
    validate_a2ui,
)
