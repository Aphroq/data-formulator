# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed parameter contracts embedded in immutable transform lineage.

Transform values are injected as a separate ``params`` object.  They are never
substituted into Python source, and the signed source must reference every
declared slot through a literal ``params["slot_id"]`` lookup.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from data_formulator.recipes.canonical import (
    FrozenJsonValue,
    canonical_json_bytes,
    thaw_json,
)
from data_formulator.recipes.spec import ParameterType, RecipeParameter


MAX_TRANSFORM_PARAMETER_SLOTS = 16
MAX_TRANSFORM_PARAMETER_BYTES = 16 * 1024
MAX_TRANSFORM_STRING_DEFAULT_BYTES = 2 * 1024


@dataclass(frozen=True, slots=True)
class TransformParameterSlot:
    """One authoring-time scalar exposed to signed transform code."""

    id: str
    name: str
    value_type: ParameterType
    default_value: FrozenJsonValue
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or len(self.name.strip()) > 200:
            raise ValueError("Transform parameter slot name is invalid")
        if (
            not isinstance(self.description, str)
            or len(self.description.strip()) > 500
        ):
            raise ValueError("Transform parameter slot description is invalid")
        value_type = ParameterType(self.value_type)
        validated = RecipeParameter(
            id=self.id,
            name=self.name.strip(),
            value_type=value_type,
            description=self.description.strip(),
            has_default=True,
            default_value=self.default_value,
        )
        default_value = validated.default_value
        if (
            value_type
            in {
                ParameterType.STRING,
                ParameterType.DATE,
                ParameterType.DATETIME,
            }
            and len(str(thaw_json(default_value)).encode("utf-8"))
            > MAX_TRANSFORM_STRING_DEFAULT_BYTES
        ):
            raise ValueError("Transform parameter slot default is too large")
        object.__setattr__(self, "name", validated.name.strip())
        object.__setattr__(self, "description", validated.description.strip())
        object.__setattr__(self, "value_type", value_type)
        object.__setattr__(self, "default_value", default_value)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "type": self.value_type.value,
            "default": thaw_json(self.default_value),
        }
        if self.description:
            result["description"] = self.description
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransformParameterSlot":
        if not isinstance(data, Mapping):
            raise TypeError("Transform parameter slot must be an object")
        required = {"id", "name", "type", "default"}
        optional = {"description"}
        if set(data) - required - optional or required - set(data):
            raise ValueError("Transform parameter slot fields are invalid")
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            value_type=ParameterType(data["type"]),
            default_value=data["default"],
        )


def normalize_transform_parameter_slots(
    raw: Sequence[Mapping[str, Any] | TransformParameterSlot] | None,
) -> tuple[TransformParameterSlot, ...]:
    """Validate and canonically order a bounded transform slot declaration."""
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise TypeError("Transform parameter slots must be an array")
    if len(raw) > MAX_TRANSFORM_PARAMETER_SLOTS:
        raise ValueError(
            f"Transform parameter slots cannot exceed {MAX_TRANSFORM_PARAMETER_SLOTS}"
        )
    slots = tuple(
        item
        if isinstance(item, TransformParameterSlot)
        else TransformParameterSlot.from_dict(item)
        for item in raw
    )
    ids = [item.id for item in slots]
    if len(ids) != len(set(ids)):
        raise ValueError("Transform parameter slot ids must be unique")
    ordered = tuple(sorted(slots, key=lambda item: item.id))
    if len(canonical_json_bytes([item.to_dict() for item in ordered])) > (
        MAX_TRANSFORM_PARAMETER_BYTES
    ):
        raise ValueError("Transform parameter slot declaration is too large")
    return ordered


def transform_parameter_defaults(
    slots: Sequence[TransformParameterSlot],
) -> dict[str, Any]:
    return {item.id: thaw_json(item.default_value) for item in slots}


def validate_transform_parameter_values(
    slots: Sequence[TransformParameterSlot],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a complete or partial value map against an immutable contract."""
    if not isinstance(values, Mapping):
        raise TypeError("Transform parameter values must be an object")
    by_id = {item.id: item for item in slots}
    unknown = sorted(set(values) - set(by_id))
    if unknown:
        raise ValueError(f"Unknown transform parameter slot(s): {unknown}")
    validated: dict[str, Any] = {}
    for slot_id, value in values.items():
        RecipeParameter(
            id=slot_id,
            name=by_id[slot_id].name,
            value_type=by_id[slot_id].value_type,
        ).validate_value(value)
        validated[slot_id] = value
    return validated


def _referenced_slot_ids(node: ast.AST) -> set[str]:
    result: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Subscript)
            and isinstance(child.value, ast.Name)
            and child.value.id == "params"
            and isinstance(child.slice, ast.Constant)
            and isinstance(child.slice.value, str)
        ):
            result.add(child.slice.value)
    return result


def _function_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


_SCALAR_ALIAS_NAMES = {
    "abs",
    "bool",
    "ceil",
    "float",
    "floor",
    "int",
    "len",
    "math",
    "max",
    "min",
    "np",
    "pd",
    "round",
    "str",
}
_SCALAR_ALIAS_CALLS = {
    "Timestamp",
    "Timedelta",
    "abs",
    "bool",
    "casefold",
    "ceil",
    "float",
    "floor",
    "int",
    "len",
    "lower",
    "lstrip",
    "max",
    "min",
    "round",
    "rstrip",
    "str",
    "strip",
    "to_datetime",
    "to_timedelta",
    "upper",
}


def _contains_parameter_data(node: ast.AST, aliases: set[str]) -> bool:
    return any(
        (
            isinstance(child, ast.Subscript)
            and isinstance(child.value, ast.Name)
            and child.value.id == "params"
        )
        or (isinstance(child, ast.Name) and child.id in aliases)
        for child in ast.walk(node)
    )


def _is_scalar_parameter_expression(node: ast.AST, aliases: set[str]) -> bool:
    """Recognize bounded scalar aliases without tainting DataFrame expressions."""
    if not _contains_parameter_data(node, aliases):
        return False
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id not in (
            aliases
            | {"params"}
            | _SCALAR_ALIAS_NAMES
            | _SCALAR_ALIAS_CALLS
        ):
            return False
        if isinstance(child, ast.Call) and _function_name(child) not in (
            _SCALAR_ALIAS_CALLS
        ):
            return False
    return True


def _assignment_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        result: set[str] = set()
        for item in node.elts:
            result.update(_assignment_names(item))
        return result
    return set()


def _scalar_parameter_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            value: ast.AST | None = None
            targets: tuple[ast.AST, ...] = ()
            if isinstance(node, ast.Assign):
                value = node.value
                targets = tuple(node.targets)
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                targets = (node.target,)
            elif isinstance(node, ast.NamedExpr):
                value = node.value
                targets = (node.target,)
            if value is None or not _is_scalar_parameter_expression(value, aliases):
                continue
            for target in targets:
                for name in _assignment_names(target):
                    if name not in aliases:
                        aliases.add(name)
                        changed = True
    return aliases


def _has_unconsumed_parameter_data(node: ast.AST, aliases: set[str]) -> bool:
    """Find a direct slot use, stopping at nested calls validated separately."""
    if isinstance(node, ast.Call):
        return _is_scalar_parameter_expression(node, aliases)
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "params"
    ):
        return True
    if isinstance(node, ast.Name) and node.id in aliases:
        return True
    return any(
        _has_unconsumed_parameter_data(child, aliases)
        for child in ast.iter_child_nodes(node)
    )


def _is_direct_parameter_lookup(node: ast.AST, aliases: set[str]) -> bool:
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "params"
    ):
        return True
    if isinstance(node, ast.Name) and node.id in aliases:
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(
            _is_direct_parameter_lookup(item, aliases)
            for item in node.elts
        )
    return False


_DYNAMIC_CODE_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "execute",
    "executemany",
    "getattr",
    "globals",
    "locals",
    "query",
    "setattr",
    "sql",
    "vars",
}

# Parameter-bearing arguments are accepted only at these data-value positions.
# A ``*`` keyword means the keyword name itself is fixed in signed source (for
# example DataFrame.assign), so only its value is dynamic.
_SAFE_PARAMETER_CALL_ARGUMENTS: dict[
    str,
    tuple[set[int] | None, set[str]],
] = {
    "Timestamp": ({0}, {"ts_input"}),
    "Timedelta": ({0}, {"value"}),
    "abs": (None, {"*"}),
    "add": ({0}, {"other", "fill_value"}),
    "assign": (set(), {"*"}),
    "between": ({0, 1}, {"left", "right"}),
    "bool": (None, {"*"}),
    "ceil": (None, {"*"}),
    "clip": ({0, 1}, {"lower", "upper"}),
    "cut": ({1}, {"bins"}),
    "diff": ({0}, {"periods"}),
    "div": ({0}, {"other", "fill_value"}),
    "eq": ({0}, {"other"}),
    "ewm": (set(), {"com", "span", "halflife", "alpha", "min_periods"}),
    "expanding": ({0}, {"min_periods"}),
    "fillna": ({0}, {"value"}),
    "float": (None, {"*"}),
    "floor": (None, {"*"}),
    "floordiv": ({0}, {"other", "fill_value"}),
    "ge": ({0}, {"other"}),
    "gt": ({0}, {"other"}),
    "head": ({0}, {"n"}),
    "int": (None, {"*"}),
    "isin": ({0}, {"values"}),
    "le": ({0}, {"other"}),
    "len": (None, {"*"}),
    "lt": ({0}, {"other"}),
    "mask": ({0, 1}, {"cond", "other"}),
    "max": (None, {"*"}),
    "min": (None, {"*"}),
    "mod": ({0}, {"other", "fill_value"}),
    "mul": ({0}, {"other", "fill_value"}),
    "ne": ({0}, {"other"}),
    "nlargest": ({0}, {"n"}),
    "nsmallest": ({0}, {"n"}),
    "nanpercentile": ({1}, {"q"}),
    "pct_change": ({0}, {"periods"}),
    "percentile": ({1}, {"q"}),
    "pow": ({0, 1}, {"other"}),
    "qcut": ({1}, {"q"}),
    "quantile": ({0}, {"q"}),
    "rank": (set(), {"ascending", "pct"}),
    "replace": ({0, 1}, {"to_replace", "value"}),
    "rolling": ({0}, {"window", "min_periods", "center", "step"}),
    "round": (None, {"decimals"}),
    "sample": ({0}, {"n", "frac", "replace", "random_state"}),
    "shift": ({0}, {"periods", "fill_value"}),
    "sort_values": (set(), {"ascending"}),
    "str": (None, {"*"}),
    "sub": ({0}, {"other", "fill_value"}),
    "tail": ({0}, {"n"}),
    "to_datetime": ({0}, {"arg"}),
    "to_timedelta": ({0}, {"arg"}),
    "truediv": ({0}, {"other", "fill_value"}),
    "where": ({0, 1, 2}, {"cond", "x", "y", "other"}),
}

_SAFE_PARAMETER_RECEIVER_CALLS = {
    "casefold",
    "lower",
    "lstrip",
    "rstrip",
    "strip",
    "upper",
}


def validate_parameterized_transform_code(
    code: str,
    slots: Sequence[TransformParameterSlot],
) -> None:
    """Require literal data lookups and reject code/string/SQL substitution paths."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Transform code cannot be empty")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError("Transform code is not valid Python") from exc

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.arg)
            and node.arg == "params"
        ) or (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == "params"
        ) or (
            isinstance(node, ast.alias)
            and (node.asname or node.name.split(".")[0]) == "params"
        ) or (
            isinstance(node, (ast.Global, ast.Nonlocal))
            and "params" in node.names
        ):
            raise ValueError(
                "Transform parameters cannot shadow the reserved params object"
            )

    declared = {item.id: item for item in slots}
    allowed_param_names: set[int] = set()
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "params"
        ):
            continue
        allowed_param_names.add(id(node.value))
        if not isinstance(node.ctx, ast.Load):
            raise ValueError("Transform parameter slots are read-only")
        if not (
            isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            raise ValueError("Transform parameter slot lookup must use a literal id")
        referenced.add(node.slice.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "params" and id(node) not in (
            allowed_param_names
        ):
            raise ValueError(
                "Transform code may only read literal parameter slots"
            )
    unknown = sorted(referenced - set(declared))
    missing = sorted(set(declared) - referenced)
    if unknown:
        raise ValueError(
            f"Transform code references unknown parameter slot(s): {unknown}"
        )
    if missing:
        raise ValueError(
            f"Transform parameter slot(s) are not used by code: {missing}"
        )

    aliases = _scalar_parameter_aliases(tree)
    local_callables = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    imported_callables = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and not (
                isinstance(node.value, ast.Name) and node.value.id == "params"
            )
            and _is_direct_parameter_lookup(node.slice, aliases)
        ):
            raise ValueError(
                "Transform parameters cannot select dynamic fields or objects"
            )

    for node in ast.walk(tree):
        slot_ids = _referenced_slot_ids(node)
        if isinstance(node, ast.JoinedStr):
            if slot_ids or _contains_parameter_data(node, aliases):
                raise ValueError(
                    "Transform parameters cannot be interpolated into strings"
                )
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            if any(
                declared[item].value_type
                in {ParameterType.STRING, ParameterType.DATE, ParameterType.DATETIME}
                for item in slot_ids
                if item in declared
            ):
                raise ValueError(
                    "Transform parameters cannot be composed into strings"
                )
        if isinstance(node, ast.Call):
            function_name = _function_name(node)
            if function_name in _DYNAMIC_CODE_CALLS:
                raise ValueError(
                    "Transform parameters cannot enter dynamic code or query text"
                )
            receiver_has_parameter = (
                isinstance(node.func, ast.Subscript)
                and _is_direct_parameter_lookup(node.func, aliases)
            ) or (
                isinstance(node.func, ast.Attribute)
                and _is_scalar_parameter_expression(node.func.value, aliases)
            )
            if receiver_has_parameter and function_name not in (
                _SAFE_PARAMETER_RECEIVER_CALLS
            ):
                raise ValueError(
                    "Transform parameters cannot select a callable or object"
                )

            parameter_positions = {
                index
                for index, argument in enumerate(node.args)
                if _has_unconsumed_parameter_data(argument, aliases)
            }
            parameter_keywords = {
                keyword.arg
                for keyword in node.keywords
                if keyword.arg is not None
                and _has_unconsumed_parameter_data(keyword.value, aliases)
            }
            if not parameter_positions and not parameter_keywords:
                continue
            if function_name in local_callables or function_name in imported_callables:
                raise ValueError(
                    "Transform parameters cannot enter locally defined callables"
                )
            rule = _SAFE_PARAMETER_CALL_ARGUMENTS.get(function_name)
            if rule is None:
                raise ValueError(
                    "Transform parameters cannot enter this function or method"
                )
            allowed_positions, allowed_keywords = rule
            if (
                allowed_positions is not None
                and not parameter_positions <= allowed_positions
            ) or (
                "*" not in allowed_keywords
                and not parameter_keywords <= allowed_keywords
            ):
                raise ValueError(
                    "Transform parameters cannot select structural call arguments"
                )
