"""Validators for config values."""

from __future__ import annotations

import re
import typing
from urllib.parse import urlparse

ConfigAllowedTypes = typing.Union[list, tuple, set, dict, str, int, float, bool, None]


class ValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Validator:
    internal_id: str = "Unknown"

    def __init__(self, validator, doc: str | dict | None = None,
                 internal_id: str | None = None):
        self.validate = validator
        self.doc = {"en": doc, "ru": doc} if isinstance(doc, str) else (doc or {})
        if internal_id:
            self.internal_id = internal_id


class Boolean(Validator):
    def __init__(self):
        super().__init__(self._validate, {"en": "boolean", "ru": "логическое значение"}, "Boolean")

    @staticmethod
    def _validate(value, /) -> bool:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "on", "1", "да", "вкл"}:
                return True
            if lowered in {"false", "no", "off", "0", "нет", "выкл"}:
                return False
            raise ValidationError(f"Passed value ({value}) is not a boolean")
        if isinstance(value, int):
            return bool(value)
        raise ValidationError(f"Passed value ({value}) is not a boolean")


class Integer(Validator):
    def __init__(self, *, minimum: int | None = None, maximum: int | None = None):
        self.minimum = minimum
        self.maximum = maximum
        super().__init__(self._validate, {"en": "integer", "ru": "целое число"}, "Integer")

    def _validate(self, value, /) -> int:
        try:
            value = int(str(value).strip())
        except (ValueError, TypeError):
            raise ValidationError(f"Passed value ({value}) is not an integer") from None
        if self.minimum is not None and value < self.minimum:
            raise ValidationError(f"Passed value ({value}) is lower than {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValidationError(f"Passed value ({value}) is greater than {self.maximum}")
        return value


class Float(Validator):
    def __init__(self, *, minimum: float | None = None, maximum: float | None = None):
        self.minimum = minimum
        self.maximum = maximum
        super().__init__(self._validate, {"en": "float", "ru": "дробное число"}, "Float")

    def _validate(self, value, /) -> float:
        try:
            value = float(str(value).strip())
        except (ValueError, TypeError):
            raise ValidationError(f"Passed value ({value}) is not a float") from None
        if self.minimum is not None and value < self.minimum:
            raise ValidationError(f"Passed value ({value}) is lower than {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValidationError(f"Passed value ({value}) is greater than {self.maximum}")
        return value


class String(Validator):
    def __init__(self, length: int | None = None, *, min_length: int | None = None):
        self.length = length
        self.min_length = min_length
        super().__init__(self._validate, {"en": "string", "ru": "строка"}, "String")

    def _validate(self, value, /) -> str:
        value = str(value)
        if self.length is not None and len(value) > self.length:
            raise ValidationError(f"Passed value is longer than {self.length} characters")
        if self.min_length is not None and len(value) < self.min_length:
            raise ValidationError(f"Passed value is shorter than {self.min_length} characters")
        return value


class Choice(Validator):
    def __init__(self, possible_values: typing.Iterable):
        self.possible_values = list(possible_values)
        super().__init__(self._validate, {"en": f"one of {self.possible_values}",
                                           "ru": f"одно из {self.possible_values}"}, "Choice")

    def _validate(self, value, /):
        if value not in self.possible_values:
            raise ValidationError(f"Passed value ({value}) is not one of {self.possible_values}")
        return value


class MultiChoice(Validator):
    def __init__(self, possible_values: typing.Iterable):
        self.possible_values = list(possible_values)
        super().__init__(self._validate, {"en": f"multiple of {self.possible_values}",
                                           "ru": f"несколько из {self.possible_values}"}, "MultiChoice")

    def _validate(self, value, /) -> list:
        if not isinstance(value, (list, tuple, set)):
            value = [value]
        for item in value:
            if item not in self.possible_values:
                raise ValidationError(f"Passed value ({item}) is not one of {self.possible_values}")
        return list(value)


class Series(Validator):
    def __init__(self, validator: Validator | None = None, *,
                 min_len: int | None = None, max_len: int | None = None,
                 fixed_len: int | None = None):
        self.validator = validator
        self.min_len = min_len
        self.max_len = max_len
        self.fixed_len = fixed_len
        super().__init__(self._validate, {"en": "list of values", "ru": "список значений"}, "Series")

    def _validate(self, value, /) -> list:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, (tuple, set)):
            value = list(value)
        if not isinstance(value, list):
            raise ValidationError(f"Passed value ({value}) is not a list")
        if self.fixed_len is not None and len(value) != self.fixed_len:
            raise ValidationError(f"List must contain exactly {self.fixed_len} items")
        if self.min_len is not None and len(value) < self.min_len:
            raise ValidationError(f"List must contain at least {self.min_len} items")
        if self.max_len is not None and len(value) > self.max_len:
            raise ValidationError(f"List must contain at most {self.max_len} items")
        if self.validator is not None:
            value = [self.validator.validate(item) for item in value]
        return value


class Link(Validator):
    def __init__(self):
        super().__init__(self._validate, {"en": "link", "ru": "ссылка"}, "Link")

    @staticmethod
    def _validate(value, /) -> str:
        value = str(value)
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationError(f"Passed value ({value}) is not a valid URL")
        return value


class RandomLinkList(list):
    def __str__(self) -> str:
        import random
        return random.choice(self) if self else ""

    def __repr__(self) -> str:
        return f"RandomLinkList({list.__repr__(self)})"


class RandomLink(Series):
    def __init__(self):
        super().__init__(Link())
        self.internal_id = "RandomLink"
        self.doc = {"en": "list of links", "ru": "список ссылок"}
        self.validate = self._validate_links

    def _validate_links(self, value, /) -> RandomLinkList:
        return RandomLinkList(Series._validate(self, value))


class RegExp(Validator):
    def __init__(self, regex: str, flags: int = 0, description: str | None = None):
        self.regex = regex
        self.flags = flags
        try:
            re.compile(regex, flags=flags)
        except re.error as e:
            raise ValueError(f"{regex} is not a valid regex") from e
        super().__init__(self._validate,
                         {"en": description or f"string matching {regex}",
                          "ru": description or f"строка по шаблону {regex}"}, "RegExp")

    def _validate(self, value, /) -> str:
        value = str(value)
        if not re.match(self.regex, value, flags=self.flags):
            raise ValidationError(f"Passed value ({value}) does not match {self.regex}")
        return value


class MaxID(Validator):
    def __init__(self):
        super().__init__(self._validate, {"en": "MAX ID", "ru": "ID в MAX"}, "MaxID")

    @staticmethod
    def _validate(value, /) -> int:
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            raise ValidationError(f"Passed value ({value}) is not a valid MAX ID") from None


class Hidden(Validator):
    def __init__(self, validator: Validator | None = None):
        self._inner = validator or String()
        super().__init__(self._validate, self._inner.doc, "Hidden")

    def _validate(self, value, /):
        return self._inner.validate(value)


class NoneType(Validator):
    def __init__(self):
        super().__init__(lambda _: None, {"en": "empty value", "ru": "пустое значение"}, "NoneType")


class Union(Validator):
    def __init__(self, *validators: Validator):
        self.validators = validators
        super().__init__(self._validate,
                         {"en": " or ".join(v.doc.get("en", v.internal_id) for v in validators),
                          "ru": " или ".join(v.doc.get("ru", v.internal_id) for v in validators)}, "Union")

    def _validate(self, value, /):
        for validator in self.validators:
            try:
                return validator.validate(value)
            except ValidationError:
                continue
        raise ValidationError(f"Passed value ({value}) is not valid")


class Emoji(Validator):
    _PATTERN = re.compile("[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]+")

    def __init__(self, length: int | None = None):
        self.length = length
        super().__init__(self._validate, {"en": "emoji", "ru": "эмодзи"}, "Emoji")

    def _validate(self, value, /) -> str:
        value = str(value)
        if not self._PATTERN.fullmatch(value):
            raise ValidationError(f"Passed value ({value}) is not an emoji")
        if self.length is not None and len(value) != self.length:
            raise ValidationError(f"Passed value must contain {self.length} emoji")
        return value