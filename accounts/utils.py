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


def generate_phone_code():
    return str(random.randint(100000, 999999))
