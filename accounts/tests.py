from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .forms import RegisterForm
from .models import ClientProfile, User
from .utils import cpf_hash, is_valid_cpf


class CPFValidationTests(TestCase):
    def test_valid_cpf_passes_check_digit_validation(self):
        self.assertTrue(is_valid_cpf("529.982.247-25"))

    def test_repeated_digits_are_invalid(self):
        self.assertFalse(is_valid_cpf("111.111.111-11"))

    def test_wrong_check_digits_are_invalid(self):
        self.assertFalse(is_valid_cpf("529.982.247-24"))

    def test_register_form_rejects_duplicate_cpf(self):
        cpf = "52998224725"
        user = User.objects.create_user(
            email="cliente@exemplo.com",
            password="Teste12345!",
            full_name="Cliente Exemplo",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash=cpf_hash(cpf),
            cpf_last_digits=cpf[-4:],
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
        )

        form = RegisterForm(
            data={
                "full_name": "Outro Cliente",
                "preferred_name": "Outro",
                "email": "outro@exemplo.com",
                "password1": "Teste12345!",
                "password2": "Teste12345!",
                "cpf": "529.982.247-25",
                "phone": "61988888888",
                "address": "Outro endereco",
            },
            files={
                "residence_proof": SimpleUploadedFile("comprovante.pdf", b"pdf"),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Ja existe um cadastro com este CPF.", form.errors["cpf"])

    def test_register_form_rejects_invalid_cpf_digits(self):
        form = RegisterForm(
            data={
                "full_name": "Cliente Invalido",
                "preferred_name": "Cliente",
                "email": "invalido@exemplo.com",
                "password1": "Teste12345!",
                "password2": "Teste12345!",
                "cpf": "529.982.247-24",
                "phone": "61999999999",
                "address": "Endereco",
            },
            files={
                "residence_proof": SimpleUploadedFile("comprovante.pdf", b"pdf"),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Informe um CPF valido.", form.errors["cpf"])
