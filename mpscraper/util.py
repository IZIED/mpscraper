import dataclasses
import decimal
import enum
import os
import pathlib
from typing import Iterator, Mapping, Union

from sqlalchemy import Integer, TypeDecorator

FileMapping = Mapping[str, Union["FileMapping", bytes]]


def chunks(seq, chunk_size: int) -> Iterator:
    """Devuelve una secuencia partida en partes de un tamaño determinado.

    La última parte entregada puede ser de menor tamaño.
    """
    assert chunk_size > 0
    for idx in range(0, len(seq), chunk_size):
        yield seq[idx : idx + chunk_size]


class IntEnum(TypeDecorator):
    _enumtype: enum.IntEnum
    impl = Integer

    def __init__(self, enumtype, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._enumtype = enumtype

    def process_bind_param(self, value: enum.IntEnum | None, dialect):
        return value.value if value else None

    def process_result_value(self, value: enum.IntEnum | None, dialect):
        return self._enumtype(value)  # type: ignore


class EntityType(enum.IntEnum):
    ENTITY = 0
    PERSON = 1
    ORGANIZATION = 2


@dataclasses.dataclass
class Money:
    amount: decimal.Decimal
    currency: str
