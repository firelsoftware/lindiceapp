from django.db import migrations, models


def migrate_personal_debt_colors(apps, schema_editor):
    PersonalDebt = apps.get_model("accounts", "PersonalDebt")
    color_map = {
        "plum": "#7a2d84",
        "blue": "#2563eb",
        "green": "#16a34a",
        "gold": "#d4a017",
        "coral": "#ff6b57",
        "slate": "#64748b",
    }

    for debt in PersonalDebt.objects.all():
        debt.color = color_map.get(debt.color, "#7a2d84")
        debt.save(update_fields=["color"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0029_personaldebt"),
    ]

    operations = [
        migrations.AlterField(
            model_name="personaldebt",
            name="color",
            field=models.CharField(default="#7a2d84", max_length=7),
        ),
        migrations.RunPython(migrate_personal_debt_colors, migrations.RunPython.noop),
    ]
