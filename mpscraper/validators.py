import itertools
import re
from typing import Literal, TypeVar

import phonenumbers

from mpscraper.util import chunks

R = TypeVar("R")
ParseResult = R | Literal[False]

NON_DIGITS_RE = re.compile(r"\D")
STANDARD_IDN_RE = re.compile(r"([\d.]+)-(\d|k)", re.IGNORECASE)
EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&’*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$"
)
PRO_CODE_PATTERN = re.compile(r"PRO?\s*[-.]?\s*(?P<code>\d+)", re.IGNORECASE)
MORE_THAN_ONE_SPACE = re.compile(r"\s\s+")
"""
Formato esperado de email, sacado de `How to Validate Emails
with Regex <https://www.abstractapi.com/tools/email-regex-guide>`_.
"""
NAME_PREFIXES_ES = {
    "de": "de",
    "de la": "de la",
    "del": "del",
    "san": "San",
}
TITLE_IGNORE_ES = {
    "y",
    "e",
    "o",
    "u",
    "a",
    "al",
    "del",
    "de",
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "en",
    "para",
}


def _throw_leniently(leninency: bool, *args, **kwargs) -> Literal[False]:
    if not leninency:
        raise ValidationError(*args, **kwargs)
    return False


class ValidationError(Exception):
    """El valor entregado no tiene un formato esperado y no se pudo validar."""

    value: str
    parsing: str
    reason: str | None
    where: int | tuple[int, int] | None

    def __init__(
        self,
        value: str,
        parsing: str,
        reason: str | None = None,
        where: int | tuple[int, int] | None = None,
    ) -> None:
        detail_message = ", " + reason if reason else ""
        if where:
            where_message = (
                f"entre índices {where[0]} y {where[1]}"
                if isinstance(where, tuple)
                else "en índice {where}"
            )
            if detail_message:
                detail_message += ", " + where_message
            else:
                detail_message = " " + where_message
        super().__init__(
            f"tratando {parsing!r}: {value!r} no es válido" + detail_message
        )
        self.value = value
        self.parsing = parsing
        self.reason = reason
        self.where = where


def rut_last_digit(rut_no_last_digit: str) -> str:
    """Calcula el dígito verificador para un RUT sin
    dígito verificador."""
    # [(2, primero), (3, segundo), ..., (7, quinto), (2, sexto), ...]
    zipped_digits = zip(
        itertools.cycle(range(2, 8)), map(int, tuple(reversed(rut_no_last_digit)))
    )
    digit = 11 - (sum(map(lambda zipped: zipped[0] * zipped[1], zipped_digits)) % 11)

    match digit:
        case 11:
            return "0"
        case 10:
            return "k"
        case n:
            return str(n)


def validate_rut(rut: str, lenient: bool = False, *, dotted=True) -> ParseResult[str]:
    """Valida y normaliza un RUT"""
    _PARSING = "RUT"
    rut = rut and rut.strip().lower()
    if not rut:
        return _throw_leniently(lenient, rut, _PARSING, "está vacío")

    standard_idn = STANDARD_IDN_RE.match(rut)

    if standard_idn:
        # formato con guión
        body = NON_DIGITS_RE.sub("", standard_idn[1])
        last_digit = standard_idn[2]
        if rut_last_digit(body) != last_digit:
            return _throw_leniently(
                lenient,
                rut,
                _PARSING,
                "el dígito verificador no corresponde",
            )
    else:
        # formato sin guion, hay que revisar si el último carácter
        # representa el dígito verificador
        body = NON_DIGITS_RE.sub("", rut)
        last_digit = body[-1]
        last_digit_guess = rut_last_digit(body[:-1])
        if last_digit_guess == last_digit:
            # los dígitos representaban el rol con el dígito
            # verificador incluido
            body = body[:-1]
        else:
            # los digitos representaban el rol sin el dígito
            # verificador, así que se le calcula
            last_digit = rut_last_digit(body)

    if len(body) < 6:
        # no aceptar roles menores a 6 dígitos de longitud
        return _throw_leniently(lenient, rut, _PARSING, "demasiado corto")

    if dotted:
        # separa los dígitos con puntos
        body = "".join(reversed(".".join(chunks("".join(reversed(body)), 3))))

    return f"{body}-{last_digit}".lower()


def validate_email_address(address: str, lenient: bool = False) -> ParseResult[str]:
    """Valida y normaliza un correo electrónico."""
    _PARSING = "correo electrónico"
    email_stripped = address and address.strip()
    if not email_stripped:
        _throw_leniently(lenient, address, _PARSING, "está vacío")
    match = EMAIL_RE.match(email_stripped)
    if match is None:
        return _throw_leniently(
            lenient,
            address,
            _PARSING,
            "hay un carácter inválido o no se ajusta al formato",
        )
    username, domain = match[0].split("@")
    return f"{username}@{domain.lower()}"


def validate_cl_phone_number(
    number: str | int, lenient: bool = False
) -> ParseResult[str]:
    """Valida y normaliza un número de teléfono chileno."""
    _PARSING = "número telefónico chileno"
    number_stripped = str(number)
    number_stripped = number_stripped and number_stripped.strip()
    if not number_stripped:
        return _throw_leniently(lenient, number_stripped, _PARSING, "está vacío")
    try:
        parsed = phonenumbers.parse(number_stripped, "CL")
    except phonenumbers.NumberParseException as err:
        return _throw_leniently(
            lenient,
            number_stripped,
            _PARSING,
            f"hubo un error en libphonenumbers: {err}",
        )
    if not phonenumbers.is_valid_number(parsed):
        return _throw_leniently(
            lenient,
            str(number),
            _PARSING,
            "hay un carácter inválido o no se ajusta al formato",
        )
    if not phonenumbers.is_possible_number(parsed):
        return _throw_leniently(
            lenient,
            str(number),
            _PARSING,
            "no es un número posible",
        )

    return phonenumbers.format_number(
        parsed, num_format=phonenumbers.PhoneNumberFormat.E164
    )


def validate_pro_code(raw_pro: str, lenient: bool = False) -> ParseResult[int]:
    match = PRO_CODE_PATTERN.match(raw_pro)
    if not match:
        return _throw_leniently(
            lenient, raw_pro, "código PRO", "no tiene el formato esperado"
        )
    code = int(match["code"])
    return code


def title_word_ignoring_es(value: str) -> str:
    """Cambia a mayúscula inicial en cada palabra a menos que la palabra pertenezca a la lista de excepciones."""
    split = [
        word.capitalize() if word.lower() not in TITLE_IGNORE_ES else word.lower()
        for word in value.split()
    ]
    return " ".join(split)


def join_prefixed_names(full_name_parts: list[str]):
    full_name_parts = list(full_name_parts)
    i = 1
    while i < len(full_name_parts) - 1:
        part = full_name_parts[i]
        if part in NAME_PREFIXES_ES:
            prefix = NAME_PREFIXES_ES[part]
            full_name_parts[i : i + 2] = [" ".join([part, full_name_parts[i + 1]])]
        i += 1
    return full_name_parts


def normalize_full_name(full_name: str) -> tuple[str, str | None]:
    full_name = full_name or ""
    parts = MORE_THAN_ONE_SPACE.sub(" ", full_name).split(" ")
    parts = [
        part.capitalize() if part not in TITLE_IGNORE_ES else part for part in parts
    ]
    parts = join_prefixed_names(parts)
    match len(parts):
        case 1:
            return parts[0], None
        case 2:
            return parts[0], parts[1]
        case 3:
            return parts[0], " ".join(parts[1:])
        case _:
            return " ".join(parts[0:-2]), " ".join(parts[-2:])
