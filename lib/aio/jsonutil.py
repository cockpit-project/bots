# Copyright (C) 2023 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import contextlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import ContextManager, TypeVar, Union

# immutable
JsonLiteral = str | float | bool | None
JsonValue = Union['JsonObject', Sequence['JsonValue'], JsonLiteral]
JsonObject = Mapping[str, JsonValue]

# mutable
JsonDocument = Union['JsonDict', 'JsonList', JsonLiteral]
JsonDict = dict[str, JsonDocument]
JsonList = list[JsonDocument]


DT = TypeVar('DT')
T = TypeVar('T')


class JsonError(Exception):
    value: object

    def __init__(self, value: object, msg: str):
        super().__init__(msg)
        self.value = value


def typechecked(value: JsonValue, expected_type: type[T]) -> T:
    """Ensure a JSON value has the expected type, returning it if so."""
    if not isinstance(value, expected_type):
        raise JsonError(value, f'must have type {expected_type.__name__}')
    return value


# We can't use None as a sentinel because it's often the actual default value
# EllipsisType is difficult because it's not available before 3.10.
# See https://peps.python.org/pep-0484/#support-for-singleton-types-in-unions
class _Empty(Enum):
    TOKEN = 0


_empty = _Empty.TOKEN


def _get(obj: JsonObject, cast: Callable[[JsonValue], T], key: str, default: DT | _Empty) -> T | DT:
    try:
        value = obj[key]
        if default is not _empty and value is default:
            return default
        return cast(obj[key])
    except KeyError:
        if default is not _empty:
            return default
        raise JsonError(obj, f"attribute '{key}' required") from None
    except JsonError as exc:
        target = f"attribute '{key}'" + (' elements:' if exc.value is not obj[key] else ':')
        raise JsonError(obj, f"{target} {exc!s}") from exc


def get_bool(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | bool:
    return _get(obj, lambda v: typechecked(v, bool), key, default)


def get_int(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | int:
    return _get(obj, lambda v: typechecked(v, int), key, default)


def get_str(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | str:
    return _get(obj, lambda v: typechecked(v, str), key, default)


def get_dict(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | JsonObject:
    return _get(obj, lambda v: typechecked(v, dict), key, default)


def get_dictv(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | Sequence[JsonObject]:
    return _get(obj, lambda v: tuple(typechecked(item, dict) for item in typechecked(v, list)), key, default)


def get_object(
    obj: JsonObject,
    key: str,
    constructor: Callable[[JsonObject], T],
    default: DT | _Empty = _empty
) -> DT | T:
    return _get(obj, lambda v: constructor(typechecked(v, dict)), key, default)


def get_str_map(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | Mapping[str, str]:
    def as_str_map(value: JsonValue) -> Mapping[str, str]:
        return {key: typechecked(value, str) for key, value in typechecked(value, dict).items()}
    return _get(obj, as_str_map, key, default)


def get_strv(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> DT | Sequence[str]:
    def as_strv(value: JsonValue) -> Sequence[str]:
        return tuple(typechecked(item, str) for item in typechecked(value, list))
    return _get(obj, as_strv, key, default)


def get_nested(obj: JsonObject, key: str, default: DT | _Empty = _empty) -> ContextManager[DT | JsonObject]:
    # workaround for https://github.com/microsoft/pyright/issues/7386
    @contextlib.contextmanager
    def wrapper() -> Iterator[DT | JsonObject]:
        try:
            yield get_dict(obj, key, default)
        except KeyError:
            if default is not _empty:
                yield default
            raise JsonError(obj, f"attribute '{key}' required") from None
        except JsonError as exc:
            target = f"attribute '{key}'" + (' elements:' if exc.value is not obj[key] else ':')
            raise JsonError(obj, f"{target} {exc!s}") from exc
    return wrapper()


def json_merge_patch(current: JsonObject, patch: JsonObject) -> JsonObject:
    """Perform a JSON merge patch (RFC 7396) using 'current' and 'patch'.
    Neither of the original dictionaries is modified — the result is returned.
    """
    # Always take a copy ('result') — we never modify the input ('current')
    result = dict(current)
    for key, patch_value in patch.items():
        if isinstance(patch_value, Mapping):
            current_value = current.get(key, None)
            if not isinstance(current_value, Mapping):
                current_value = {}
            result[key] = json_merge_patch(current_value, patch_value)
        elif patch_value is not None:
            result[key] = patch_value
        else:
            result.pop(key, None)

    return result


def parse_filename(value: JsonValue) -> str | None:
    # magic: must look exactly like [{file="filename"}]
    if not isinstance(value, Sequence) or len(value) != 1:
        return None
    item, = value
    if not isinstance(item, Mapping) or len(item) != 1:
        return None
    (key, filename), = item.items()
    if key != 'file' or not isinstance(filename, str):
        return None
    return filename


def load_external_files(obj: JsonObject, path: Path) -> JsonObject:
    """Replace any [{"file": "filename"}] entries in a document with the
    contents of the named files. The original dictionary is not modified — the
    result is returned.
    """
    result = {}
    for key, value in obj.items():
        if filename := parse_filename(value):
            value = (path / filename).read_text()
        elif isinstance(value, dict):
            value = load_external_files(value, path)
        result[key] = value
    return result
