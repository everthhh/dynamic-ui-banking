"""Validador de mensajes A2UI contra el catalogo.

El punto de este modulo no es "rechazar". Es escribir errores que el modelo
pueda arreglar en el siguiente turno sin ayuda humana. Por eso cada mensaje de
error dice: que componente, que prop, que estaba mal y cuales son los valores
validos. Eso es lo que hace que el ciclo de reintento converja en una vuelta
en lugar de tres.

Uso:

    from a2ui import validate_a2ui
    res = validate_a2ui(mensajes)
    if not res.ok:
        # res.para_el_modelo() -> texto que va como tool_result is_error
        ...
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
CATALOG: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

COMPONENTES: dict[str, Any] = CATALOG["components"]
ACCIONES: dict[str, Any] = CATALOG["acciones"]
CATALOG_ID: str = CATALOG["catalogId"]
A2UI_VERSION: str = CATALOG["a2uiVersion"]

CLAVES_MENSAJE = ("createSurface", "updateComponents", "updateDataModel", "deleteSurface")

# Props que cualquier componente acepta sin declararlas.
PROPS_IMPLICITAS = frozenset({"id", "component", "children"})

COLUMNAS_INSTRUMENT_TABLE = frozenset({
    "nombre", "clase", "emisor", "rend_esperado_anual", "rend_neto_anual",
    "volatilidad_anual", "comision_anual", "riesgo_1a5", "liquidez",
    "plazo_dias", "monto_minimo",
})


@dataclass
class ValidationResult:
    ok: bool
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    superficies: list[str] = field(default_factory=list)

    def para_el_modelo(self) -> str:
        """Texto que se devuelve como tool_result con is_error=true."""
        lineas = [
            "El blueprint A2UI no pasó la validación contra el catálogo. "
            "Corrige y vuelve a llamar `render_surface`. Errores:"
        ]
        lineas += [f"  {i}. {e}" for i, e in enumerate(self.errores, 1)]
        if self.avisos:
            lineas.append("Avisos (no bloquean, pero revísalos):")
            lineas += [f"  - {a}" for a in self.avisos]
        return "\n".join(lineas)


def _es_binding(valor: Any) -> bool:
    return isinstance(valor, dict) and set(valor.keys()) == {"path"}


def _tipo_ok(valor: Any, tipo: str) -> bool:
    if tipo == "string":
        return isinstance(valor, str)
    if tipo == "number":
        return isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if tipo == "boolean":
        return isinstance(valor, bool)
    if tipo == "array":
        return isinstance(valor, list)
    if tipo == "object":
        return isinstance(valor, dict)
    if tipo in ("enum", "action"):
        return True          # se validan aparte
    return True


def _nombre_de_evento(valor: Any) -> Any:
    """Extrae `event.name` de una `action` bien formada; None si no aplica."""
    if not isinstance(valor, dict):
        return None
    evento = valor.get("event")
    return evento.get("name") if isinstance(evento, dict) else None


def _validar_action(valor: Any, ruta: str, errores: list[str]) -> None:
    """Valida el prop `action` de un componente contra `common_types.json#/$defs/Action`
    del spec A2UI v0.9: dispara un evento de servidor -> `{"event": {"name", "context"?}}`.
    Este catálogo no declara funciones de cliente, así que `functionCall` no aplica aquí.
    """
    if not isinstance(valor, dict):
        errores.append(
            f"{ruta}: `action` debe ser un objeto {{event: {{name, context?}}}}, "
            f"llegó {type(valor).__name__}."
        )
        return
    if "functionCall" in valor:
        errores.append(
            f"{ruta}: `functionCall` no está soportado; este catálogo solo declara "
            "acciones de servidor. Usa {\"event\": {\"name\", \"context\"?}}."
        )
        return
    evento = valor.get("event")
    sobrantes_top = set(valor) - {"event"}
    if sobrantes_top:
        errores.append(
            f"{ruta}: claves no permitidas en `action`: {', '.join(sorted(sobrantes_top))}. "
            "Solo `event`."
        )
    if not isinstance(evento, dict):
        errores.append(f"{ruta}: falta `event` (objeto {{name, context?}}) en la acción.")
        return
    nombre = evento.get("name")
    if nombre is None:
        errores.append(f"{ruta}.event: falta `name`.")
        return
    if nombre not in ACCIONES:
        errores.append(
            f"{ruta}.event: acción desconocida {nombre!r}. "
            f"Acciones declaradas en el catálogo: {', '.join(sorted(ACCIONES))}."
        )
    sobrantes = set(evento) - {"name", "context"}
    if sobrantes:
        errores.append(
            f"{ruta}.event: claves no permitidas: {', '.join(sorted(sobrantes))}. "
            "Solo `name` y `context`."
        )
    if "context" in evento and not isinstance(evento["context"], dict):
        errores.append(f"{ruta}.event: `context` debe ser un objeto.")


def _validar_componente(nodo: Any, idx: int, errores: list[str], avisos: list[str]) -> str | None:
    ruta = f"updateComponents.components[{idx}]"
    if not isinstance(nodo, dict):
        errores.append(f"{ruta}: cada componente debe ser un objeto.")
        return None

    cid = nodo.get("id")
    nombre = nodo.get("component")
    if not isinstance(cid, str) or not cid:
        errores.append(f"{ruta}: falta `id` (string no vacío).")
    if not isinstance(nombre, str):
        if isinstance(nodo.get("type"), str):
            errores.append(
                f"{ruta}: el campo se llama `component`, no `type`. Cambia "
                f"\"type\": {nodo['type']!r} por \"component\": {nodo['type']!r}."
            )
        else:
            errores.append(f"{ruta}: falta `component`.")
        return cid if isinstance(cid, str) else None

    if isinstance(nodo.get("props"), dict):
        errores.append(
            f"{ruta} ({nombre}): las props van sueltas en el objeto del componente, "
            f"no anidadas bajo `props`. Sube estas claves al nivel de `id`/`component`: "
            f"{', '.join(sorted(nodo['props']))}."
        )

    spec = COMPONENTES.get(nombre)
    if spec is None:
        dominio = sorted(k for k in COMPONENTES if "." in k)
        primitivos = sorted(k for k in COMPONENTES if "." not in k)
        errores.append(
            f"{ruta}: el componente {nombre!r} no está en el catálogo y el renderer lo "
            f"va a ignorar. Componentes de dominio: {', '.join(dominio)}. "
            f"Primitivos: {', '.join(primitivos)}."
        )
        return cid if isinstance(cid, str) else None

    props_spec: dict[str, Any] = spec.get("props", {})

    # children
    if "children" in nodo:
        if not spec.get("children"):
            errores.append(
                f"{ruta} ({nombre}): este componente no acepta `children`. "
                "Solo Column, Row y Card anidan."
            )
        elif not isinstance(nodo["children"], list) or not all(
                isinstance(c, str) for c in nodo["children"]):
            errores.append(f"{ruta} ({nombre}): `children` debe ser una lista de ids.")

    # props declaradas
    for prop, spec_prop in props_spec.items():
        presente = prop in nodo
        if spec_prop.get("requerido") and not presente:
            errores.append(
                f"{ruta} ({nombre}): falta la prop obligatoria `{prop}`"
                + (f" — {spec_prop['descripcion']}" if spec_prop.get("descripcion") else "")
            )
            continue
        if not presente:
            continue

        valor = nodo[prop]
        tipo = spec_prop.get("tipo", "string")

        if _es_binding(valor):
            if not spec_prop.get("bindable"):
                errores.append(
                    f"{ruta} ({nombre}): `{prop}` no es enlazable; pásale un valor literal "
                    "en lugar de {\"path\": ...}."
                )
            elif not str(valor["path"]).startswith("/"):
                errores.append(
                    f"{ruta} ({nombre}): la ruta de `{prop}` debe empezar con '/', "
                    f"llegó {valor['path']!r}."
                )
            continue

        if tipo == "action":
            _validar_action(valor, f"{ruta} ({nombre}).{prop}", errores)
            continue

        if tipo == "enum":
            validos = spec_prop.get("valores", [])
            if valor not in validos:
                errores.append(
                    f"{ruta} ({nombre}): `{prop}` = {valor!r} no es válido. "
                    f"Valores: {', '.join(map(str, validos))}."
                )
            continue

        if not _tipo_ok(valor, tipo):
            errores.append(
                f"{ruta} ({nombre}): `{prop}` debe ser {tipo}, llegó "
                f"{type(valor).__name__}."
            )

    # props no declaradas
    sobrantes = set(nodo) - PROPS_IMPLICITAS - set(props_spec)
    if sobrantes:
        errores.append(
            f"{ruta} ({nombre}): props no declaradas en el catálogo: "
            f"{', '.join(sorted(sobrantes))}. Props válidas: "
            f"{', '.join(sorted(props_spec)) or '(ninguna)'}."
        )

    # reglas especificas de dominio
    if nombre == "inv.OrderTicket" and nodo.get("requiresConfirmation") is False:
        errores.append(
            f"{ruta} (inv.OrderTicket): `requiresConfirmation` no puede ser false. "
            "Toda orden se confirma en dos pasos."
        )
    if nombre == "inv.InstrumentTable" and isinstance(nodo.get("columns"), list):
        malas = [c for c in nodo["columns"] if c not in COLUMNAS_INSTRUMENT_TABLE]
        if malas:
            errores.append(
                f"{ruta} (inv.InstrumentTable): columnas inválidas: {', '.join(map(str, malas))}. "
                f"Válidas: {', '.join(sorted(COLUMNAS_INSTRUMENT_TABLE))}."
            )
    if nombre == "inv.RiskProfiler":
        accion = nodo.get("action")
        nombre_evento = _nombre_de_evento(accion)
        if accion is not None and nombre_evento not in (None, "profile_done"):
            errores.append(
                f"{ruta} (inv.RiskProfiler): su `action.event.name` debe ser `profile_done`, "
                f"llegó {nombre_evento!r}."
            )
    if nombre == "inv.OrderTicket":
        accion = nodo.get("action")
        nombre_evento = _nombre_de_evento(accion)
        if accion is not None and nombre_evento not in (None, "place_order"):
            errores.append(
                f"{ruta} (inv.OrderTicket): su `action.event.name` debe ser `place_order`, "
                f"llegó {nombre_evento!r}."
            )
    if nombre == "pay.PaymentTicket":
        if nodo.get("requiresConfirmation") is False:
            errores.append(
                f"{ruta} (pay.PaymentTicket): `requiresConfirmation` no puede ser false. "
                "Todo pago, transferencia o retiro se confirma en dos pasos."
            )
        accion = nodo.get("action")
        nombre_evento = _nombre_de_evento(accion)
        if accion is not None and nombre_evento not in (None, "confirm_payment"):
            errores.append(
                f"{ruta} (pay.PaymentTicket): su `action.event.name` debe ser "
                f"`confirm_payment`, llegó {nombre_evento!r}."
            )

    return cid if isinstance(cid, str) else None


def _validar_mensaje(msg: Any, idx: int, res: ValidationResult) -> None:
    ruta = f"messages[{idx}]"
    if not isinstance(msg, dict):
        res.errores.append(f"{ruta}: cada mensaje debe ser un objeto JSON.")
        return

    version = msg.get("version")
    if version != A2UI_VERSION:
        res.errores.append(
            f"{ruta}: `version` debe ser {A2UI_VERSION!r}, llegó {version!r}."
        )

    presentes = [k for k in CLAVES_MENSAJE if k in msg]
    if len(presentes) != 1:
        res.errores.append(
            f"{ruta}: un mensaje lleva exactamente una acción. "
            f"Encontré {len(presentes)} ({', '.join(presentes) or 'ninguna'}). "
            f"Opciones: {', '.join(CLAVES_MENSAJE)}."
        )
        return

    sobrantes = set(msg) - {"version"} - set(presentes)
    if sobrantes:
        res.errores.append(
            f"{ruta}: claves inesperadas al nivel del mensaje: {', '.join(sorted(sobrantes))}."
        )

    clave = presentes[0]
    cuerpo = msg[clave]
    if not isinstance(cuerpo, dict):
        res.errores.append(f"{ruta}.{clave}: debe ser un objeto.")
        return

    if not cuerpo.get("surfaceId"):
        res.errores.append(f"{ruta}.{clave}: falta `surfaceId`.")

    if clave == "createSurface":
        res.superficies.append(str(cuerpo.get("surfaceId")))
        cid = cuerpo.get("catalogId")
        if cid != CATALOG_ID:
            res.errores.append(
                f"{ruta}.createSurface: `catalogId` debe ser {CATALOG_ID!r}, llegó {cid!r}."
            )
        tema = cuerpo.get("theme")
        if tema is not None and not isinstance(tema, dict):
            res.errores.append(f"{ruta}.createSurface: `theme` debe ser un objeto.")
        sobrantes_cs = set(cuerpo) - {"surfaceId", "catalogId", "theme"}
        if sobrantes_cs:
            res.errores.append(
                f"{ruta}.createSurface: claves no permitidas: {', '.join(sorted(sobrantes_cs))}. "
                "Solo `surfaceId`, `catalogId` y `theme`."
            )

    elif clave == "updateComponents":
        comps = cuerpo.get("components")
        if not isinstance(comps, list) or not comps:
            res.errores.append(
                f"{ruta}.updateComponents: `components` debe ser una lista no vacía."
            )
            return
        ids: list[str] = []
        for j, nodo in enumerate(comps):
            cid = _validar_componente(nodo, j, res.errores, res.avisos)
            if cid:
                ids.append(cid)
        duplicados = {i for i in ids if ids.count(i) > 1}
        if duplicados:
            res.errores.append(
                f"{ruta}.updateComponents: ids repetidos: {', '.join(sorted(duplicados))}."
            )
        if "root" not in ids:
            res.errores.append(
                f"{ruta}.updateComponents: falta el componente con id `root`. "
                "El renderer monta el árbol desde ahí."
            )
        conocidos = set(ids)
        for nodo in comps:
            if isinstance(nodo, dict) and isinstance(nodo.get("children"), list):
                huerfanos = [c for c in nodo["children"] if c not in conocidos]
                if huerfanos:
                    res.errores.append(
                        f"{ruta}.updateComponents: {nodo.get('id')!r} referencia hijos que "
                        f"no vienen en este mensaje: {', '.join(map(str, huerfanos))}."
                    )
        referenciados = {
            c for nodo in comps if isinstance(nodo, dict)
            for c in (nodo.get("children") or [])
        }
        sueltos = conocidos - referenciados - {"root"}
        if sueltos:
            res.avisos.append(
                f"{ruta}.updateComponents: estos componentes no los alcanza nadie desde "
                f"`root` y no se van a pintar: {', '.join(sorted(sueltos))}."
            )

    elif clave == "updateDataModel":
        path = cuerpo.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            res.errores.append(
                f"{ruta}.updateDataModel: `path` debe ser un string que empiece con '/', "
                f"llegó {path!r}."
            )
        if "value" not in cuerpo:
            if "model" in cuerpo or "dataModel" in cuerpo:
                clave_usada = "model" if "model" in cuerpo else "dataModel"
                res.errores.append(
                    f"{ruta}.updateDataModel: no existe `{clave_usada}`. Usa `path` "
                    "(la ruta que cambia, ej. '/perfilador') y `value` (el valor nuevo "
                    f"en esa ruta) en vez de mandar todo el modelo junto en `{clave_usada}`."
                )
            else:
                res.errores.append(f"{ruta}.updateDataModel: falta `value`.")
        sobrantes_udm = set(cuerpo) - {"surfaceId", "path", "value"}
        if sobrantes_udm:
            res.errores.append(
                f"{ruta}.updateDataModel: claves no permitidas: {', '.join(sorted(sobrantes_udm))}. "
                "Solo `surfaceId`, `path` y `value`."
            )

    elif clave == "deleteSurface":
        # Solo necesita `surfaceId`, ya validado arriba. Nada más que revisar:
        # es una señal de "quita esta superficie", no un árbol de componentes.
        sobrantes_ds = set(cuerpo) - {"surfaceId"}
        if sobrantes_ds:
            res.errores.append(
                f"{ruta}.deleteSurface: claves no permitidas: {', '.join(sorted(sobrantes_ds))}. "
                "Solo `surfaceId`."
            )


def validate_a2ui(mensajes: Any) -> ValidationResult:
    """Valida un arreglo de mensajes A2UI contra el catalogo.

    Acepta tambien `{"messages": [...]}` porque es la forma en la que llega el
    argumento de la tool `render_surface`.
    """
    res = ValidationResult(ok=True)

    if isinstance(mensajes, dict) and "messages" in mensajes:
        mensajes = mensajes["messages"]
    if isinstance(mensajes, dict):
        mensajes = [mensajes]
    if not isinstance(mensajes, list):
        res.ok = False
        res.errores.append(
            "`messages` debe ser una lista de mensajes A2UI, llegó "
            f"{type(mensajes).__name__}."
        )
        return res
    if not mensajes:
        res.ok = False
        res.errores.append("`messages` vino vacío: no hay nada que pintar.")
        return res

    for i, msg in enumerate(mensajes):
        _validar_mensaje(msg, i, res)

    res.ok = not res.errores
    return res


def componentes_disponibles() -> Iterable[str]:
    return sorted(COMPONENTES)
