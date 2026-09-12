"""Genera todo lo que se deriva de a2ui/catalog.json.

    python -m scripts.gen_catalog_artifacts            # escribe
    python -m scripts.gen_catalog_artifacts --check    # falla si esta desalineado

Salidas:
  agent/catalog_prompt.md       fragmento del system prompt (cacheado por Anthropic)
  web/src/catalog.types.ts      tipos TypeScript del renderer

El test de contrato corre esto con --check. Si alguien edita el catalogo y no
regenera, el test falla: es lo que mantiene alineados prompt, validador y front.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from a2ui.models import ACCIONES, CATALOG, CATALOG_ID, COMPONENTES, A2UI_VERSION

ROOT = Path(__file__).resolve().parent.parent
PROMPT_OUT = ROOT / "agent" / "catalog_prompt.md"
TS_OUT = ROOT / "web" / "src" / "catalog.types.ts"

AVISO = "<!-- GENERADO por scripts/gen_catalog_artifacts.py desde a2ui/catalog.json. No editar a mano. -->"
AVISO_TS = "// GENERADO por scripts/gen_catalog_artifacts.py desde a2ui/catalog.json. No editar a mano."


def _tipo_prompt(spec: dict) -> str:
    tipo = spec.get("tipo", "string")
    if tipo == "enum":
        return "|".join(map(str, spec.get("valores", [])))
    return tipo


def construir_prompt() -> str:
    l = [AVISO, "", "## Catálogo de componentes (A2UI " + A2UI_VERSION + ")", "",
         f"`catalogId`: `{CATALOG_ID}`", "",
         "Reglas del catálogo:"]
    l += [f"- {r}" for r in CATALOG["reglas"]]
    l += ["", "### Acciones declaradas", "",
          "| acción | cuándo | contexto que debe viajar |", "|---|---|---|"]
    for nombre, spec in ACCIONES.items():
        efecto = " **(mueve dinero)**" if spec.get("efecto") else ""
        l.append(f"| `{nombre}` | {spec['descripcion']}{efecto} | "
                 f"{', '.join(f'`{c}`' for c in spec.get('contexto', [])) or '—'} |")

    for grupo, titulo in (("dominio", "Componentes de dominio"), ("primitivo", "Primitivos")):
        l += ["", f"### {titulo}", ""]
        for nombre, spec in COMPONENTES.items():
            if spec.get("tipo") != grupo:
                continue
            l.append(f"#### `{nombre}`")
            l.append(f"*Cuándo:* {spec['cuando']}")
            if spec.get("children"):
                l.append("*Anida:* sí, vía `children: [ids]`.")
            props = spec.get("props", {})
            if props:
                l.append("")
                l.append("| prop | tipo | obl. | enlazable | nota |")
                l.append("|---|---|---|---|---|")
                for p, ps in props.items():
                    l.append(
                        f"| `{p}` | {_tipo_prompt(ps)} | "
                        f"{'sí' if ps.get('requerido') else '—'} | "
                        f"{'sí' if ps.get('bindable') else '—'} | "
                        f"{ps.get('descripcion', '')} |"
                    )
            l.append("")
    return "\n".join(l).rstrip() + "\n"


def _tipo_ts(spec: dict) -> str:
    tipo = spec.get("tipo", "string")
    base = {
        "string": "string",
        "number": "number",
        "boolean": "boolean",
        "array": "unknown[]",
        "object": "Record<string, unknown>",
        "action": "A2UIAction",
    }.get(tipo)
    if tipo == "enum":
        base = " | ".join(json.dumps(v) for v in spec.get("valores", []))
    base = base or "unknown"
    if spec.get("bindable"):
        base = f"{base} | Binding"
    return base


def construir_ts() -> str:
    l = [AVISO_TS, "",
         "export const CATALOG_ID = " + json.dumps(CATALOG_ID) + ";",
         "export const A2UI_VERSION = " + json.dumps(A2UI_VERSION) + ";", "",
         "export type Binding = { path: string };", "",
         "export type ActionName =",
         "  " + "\n  ".join(f"| {json.dumps(a)}" for a in ACCIONES) + ";", "",
         "export type A2UIAction = {",
         "  name: ActionName;",
         "  surfaceId?: string;",
         "  context?: Record<string, unknown>;",
         "};", ""]

    nombres_ts: list[str] = []
    for nombre, spec in COMPONENTES.items():
        tipo_nombre = "Props" + "".join(
            parte[:1].upper() + parte[1:] for parte in nombre.replace("inv.", "Inv_").split(".")
        ).replace("Inv_", "Inv")
        nombres_ts.append((nombre, tipo_nombre))
        l.append(f"/** {spec['cuando']} */")
        l.append(f"export type {tipo_nombre} = {{")
        l.append("  id: string;")
        l.append(f"  component: {json.dumps(nombre)};")
        if spec.get("children"):
            l.append("  children?: string[];")
        for p, ps in spec.get("props", {}).items():
            opcional = "" if ps.get("requerido") else "?"
            l.append(f"  {p}{opcional}: {_tipo_ts(ps)};")
        l.append("};")
        l.append("")

    l.append("export type AnyComponent =")
    l.append("  " + "\n  ".join(f"| {t}" for _, t in nombres_ts) + ";")
    l.append("")
    l.append("export const COMPONENT_NAMES = [")
    l.append("  " + ", ".join(json.dumps(n) for n, _ in nombres_ts))
    l.append("] as const;")
    l.append("")
    l.append("export type ComponentName = (typeof COMPONENT_NAMES)[number];")
    l.append("")
    l.append("export const THEME = " + json.dumps(CATALOG["theme"], indent=2,
                                                  ensure_ascii=False) + " as const;")
    l.append("")
    return "\n".join(l)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="no escribe; devuelve 1 si los artefactos están desalineados")
    args = ap.parse_args()

    salidas = {PROMPT_OUT: construir_prompt(), TS_OUT: construir_ts()}

    if args.check:
        desalineados = [
            str(p.relative_to(ROOT)) for p, contenido in salidas.items()
            if not p.exists() or p.read_text(encoding="utf-8") != contenido
        ]
        if desalineados:
            print("Artefactos desalineados con a2ui/catalog.json:")
            for d in desalineados:
                print(f"  - {d}")
            print("Corre `make catalog` para regenerarlos.")
            return 1
        print("Artefactos alineados con el catálogo.")
        return 0

    for p, contenido in salidas.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
        print(f"escrito {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
