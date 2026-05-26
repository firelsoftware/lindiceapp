import hashlib
import hmac
import random
import re

from django.conf import settings


def clean_digits(value):
    return re.sub(r"\D", "", value or "")


def cpf_hash(cpf):
    cpf_digits = clean_digits(cpf)
    secret = getattr(settings, "CPF_HASH_SECRET", settings.SECRET_KEY)

    return hmac.new(
        secret.encode(),
        cpf_digits.encode(),
        hashlib.sha256,
    ).hexdigest()


def cpf_last_digits(cpf):
    return clean_digits(cpf)[-4:]


def is_valid_cpf(cpf):
    cpf_digits = clean_digits(cpf)

    if len(cpf_digits) != 11:
        return False

    if cpf_digits == cpf_digits[0] * 11:
        return False

    numbers = [int(digit) for digit in cpf_digits]

    for digit_index in (9, 10):
        factor = digit_index + 1
        total = sum(numbers[index] * (factor - index) for index in range(digit_index))
        check_digit = (total * 10) % 11

        if check_digit == 10:
            check_digit = 0

        if numbers[digit_index] != check_digit:
            return False

    return True


def generate_phone_code():
    return str(random.randint(100000, 999999))
