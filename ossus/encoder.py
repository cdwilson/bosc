import dataclasses as dc
import datetime
import ipaddress
import operator
import pathlib
from enum import Enum
from typing import (
    Any,
    Callable,
    Container,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    Tuple, Set,
)

import pydantic

import ossus

SingleArgCallable = Callable[[Any], Any]
DEFAULT_CUSTOM_ENCODERS: MutableMapping[type, SingleArgCallable] = {
    ipaddress.IPv4Address: str,
    ipaddress.IPv4Interface: str,
    ipaddress.IPv4Network: str,
    ipaddress.IPv6Address: str,
    ipaddress.IPv6Interface: str,
    ipaddress.IPv6Network: str,
    pathlib.PurePath: str,
    pydantic.SecretBytes: pydantic.SecretBytes.get_secret_value,
    pydantic.SecretStr: pydantic.SecretStr.get_secret_value,
    datetime.datetime: lambda d: d.timestamp(),
    datetime.date: lambda d: d.isoformat(),
    datetime.timedelta: operator.methodcaller("total_seconds"),
    Enum: operator.attrgetter("value"),
}


@dc.dataclass
class Encoder:
    """
    JSON encoding class
    """

    exclude: Container[str] = frozenset()
    custom_encoders: Mapping[type, SingleArgCallable] = dc.field(
        default_factory=dict
    )
    to_db: bool = False
    keep_nulls: bool = True

    def _encode_document(self, obj: "beanie.Document") -> Mapping[str, Any]:
        obj.parse_store()
        settings = obj.get_settings()
        obj_dict = {}
        if obj._class_id:
            obj_dict[settings.class_id] = obj._class_id

        sub_encoder = Encoder(
            # don't propagate self.exclude to subdocuments
            custom_encoders=settings.json_encoders,
            to_db=self.to_db,
            keep_nulls=self.keep_nulls,
        )
        for key, value in self._iter_model_items(obj):
            obj_dict[key] = sub_encoder.encode(value)
        return obj_dict

    def encode(self, obj: Any) -> Any:
        if self.custom_encoders:
            encoder = _get_encoder(obj, self.custom_encoders)
            if encoder is not None:
                return encoder(obj)

        encoder = _get_encoder(obj, DEFAULT_CUSTOM_ENCODERS)
        if encoder is not None:
            return encoder(obj)

        if isinstance(obj, ossus.Document):
            return self._encode_document(obj)
        if isinstance(obj, pydantic.RootModel):
            return self.encode(obj.root)
        if isinstance(obj, pydantic.BaseModel):
            items = self._iter_model_items(obj)
            return {key: self.encode(value) for key, value in items}
        if isinstance(obj, Mapping):
            return {
                key if isinstance(key, Enum) else str(key): self.encode(value)
                for key, value in obj.items()
            }
        if isinstance(obj, Iterable):
            return [self.encode(value) for value in obj]

        raise ValueError(f"Cannot encode {obj!r}")

    def _iter_model_items(
            self, obj: pydantic.BaseModel
    ) -> Iterable[Tuple[str, Any]]:
        exclude, keep_nulls = self.exclude, self.keep_nulls
        for key, value in obj.__iter__():
            field_info = obj.model_fields.get(key)
            if field_info is not None:
                key = field_info.alias or key
            if key not in exclude and (value is not None or keep_nulls):
                yield key, value


def _get_encoder(
        obj: Any, custom_encoders: Mapping[type, SingleArgCallable]
) -> Optional[SingleArgCallable]:
    encoder = custom_encoders.get(type(obj))
    if encoder is not None:
        return encoder
    for cls, encoder in custom_encoders.items():
        if isinstance(obj, cls):
            return encoder
    return None


def get_dict(
        document: "Document",
        to_db: bool = False,
        exclude: Optional[Set[str]] = None,
        keep_nulls: bool = True,
):
    if exclude is None:
        exclude = set()
    if document.id is None:
        exclude.add("_id")
    if not document.get_settings().use_revision:
        exclude.add("revision_id")
    encoder = Encoder(exclude=exclude, to_db=to_db, keep_nulls=keep_nulls)
    return encoder.encode(document)