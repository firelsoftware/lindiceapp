import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cria ou atualiza o administrador inicial a partir de variaveis de ambiente."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        full_name = os.environ.get("DJANGO_SUPERUSER_FULL_NAME", "Administrador Lindice")
        preferred_name = os.environ.get("DJANGO_SUPERUSER_PREFERRED_NAME", "Administrador")

        if not email or not password:
            self.stdout.write("Administrador inicial nao configurado.")
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={
                "full_name": full_name,
                "preferred_name": preferred_name,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        changed_fields = []

        for field, value in {
            "full_name": full_name,
            "preferred_name": preferred_name,
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        }.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)

        user.set_password(password)
        changed_fields.append("password")
        user.save(update_fields=changed_fields)

        action = "criado" if created else "atualizado"
        self.stdout.write(self.style.SUCCESS(f"Administrador inicial {action}: {email}"))
