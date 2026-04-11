from __future__ import annotations

import operator
from collections.abc import Iterable
from typing import SupportsIndex, TypeVar

T = TypeVar("T")


class AppendOnlyList(list[T]):
    """List wrapper that forbids overwrite, delete, and slice assignment (D-2 §6)."""

    def __setitem__(self, key: SupportsIndex | slice, value: T | Iterable[T]) -> None:
        raise TypeError("AppendOnlyList does not support item reassignment")

    def __delitem__(self, key: SupportsIndex | slice) -> None:
        raise TypeError("AppendOnlyList does not support deletion")

    def insert(self, index: SupportsIndex, value: T) -> None:
        idx = operator.index(index)
        if idx != len(self):
            raise TypeError("AppendOnlyList only permits append-at-end semantics")
        super().insert(idx, value)

    def pop(self, index: SupportsIndex = -1) -> T:
        raise TypeError("AppendOnlyList does not support pop")

    def remove(self, value: T) -> None:
        raise TypeError("AppendOnlyList does not support remove")

    def clear(self) -> None:
        raise TypeError("AppendOnlyList does not support clear")

    def __iadd__(self, x: Iterable[T]) -> AppendOnlyList[T]:  # type: ignore[override,misc]
        super().__iadd__(x)
        return self
