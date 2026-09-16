"""Importação idempotente dos manifestos revisados; fotos ficam no storage da loja."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.catalog_pricing import pdf_catalog_price
from accounts.models import SupplierProduct, SupplierProductPhoto, SupplierProductVariant

ROOT = Path(__file__).resolve().parents[2] / 'seed' / 'catalogos_202609'


def read_manifest(path):
    data = json.loads(path.read_text(encoding='utf8'))
    seen = set()
    alias_owners = {}
    for item in data['products']:
        code = item['code']
        if code in seen:
            raise CommandError(f'Código repetido: {code}')
        seen.add(code)
        for alias in item.get('aliases', []):
            if alias in alias_owners and alias_owners[alias] != code:
                raise CommandError(f'Equivalência antiga ambígua: {alias}')
            alias_owners[alias] = code
        if 'relog' in item['name'].lower() or 'relóg' in item['name'].lower():
            raise CommandError('Relógios não fazem parte desta importação.')
        if pdf_catalog_price(item['retail']) != Decimal(item['price']):
            raise CommandError(f'Preço divergente: {code}')
        if item['quality'] not in ('Premium', 'Original') or not item['photos']:
            raise CommandError(f'Produto incompleto: {code}')
        for photo in item['photos']:
            photo_path = (path.parent / photo['file']).resolve()
            if not photo_path.is_relative_to(path.parent.resolve()) or not photo_path.is_file():
                raise CommandError(f'Foto ausente ou fora do catálogo: {code}')
            if hashlib.sha256(photo_path.read_bytes()).hexdigest() != photo['sha256']:
                raise CommandError(f'Foto modificada sem revisão: {code}')
    for code in data.get('withdrawn', []):
        # Produto sem nenhuma foto publicável sai do ar, mas continua no banco com seus pedidos.
        if code in seen:
            raise CommandError(f'Código retirado e importado ao mesmo tempo: {code}')
    return data


class Command(BaseCommand):
    help = 'Publica somente os produtos dos manifestos revisados, preservando alterações posteriores.'

    def add_arguments(self, parser):
        parser.add_argument('--catalogo')
        parser.add_argument('--ensaio', action='store_true')

    def handle(self, *args, **options):
        paths = sorted(ROOT.glob('*/manifest.json'))
        if options['catalogo']:
            paths = [p for p in paths if p.parent.name == options['catalogo']]
            if not paths:
                raise CommandError('Catálogo não encontrado.')
        # Valida todos os arquivos antes da primeira gravação/upload.
        manifests = [(path, read_manifest(path)) for path in paths]
        for path, data in manifests:
            created = updated = unchanged = 0
            for item in data['products']:
                if options['ensaio']:
                    self.stdout.write(f"{item['code']} | {item['name']} | R$ {item['price']} | {len(item['photos'])} fotos")
                    continue
                result = self.import_product(path, data, item)
                created += result == 'created'
                updated += result == 'updated'
                unchanged += result == 'unchanged'
            withdrawn = 0
            if not options['ensaio'] and data.get('withdrawn'):
                withdrawn = SupplierProduct.objects.filter(
                    source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
                    supplier_code__in=data['withdrawn']).update(is_visible=False, is_active=False)
            self.stdout.write(f"{data['catalog']}: {created} criados, {updated} atualizados, {unchanged} já importados; "
                              f"{withdrawn} retirados do ar; {len(data.get('pending', []))} pendentes de revisão.")

    @transaction.atomic
    def import_product(self, path, data, item):
        source = SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA
        product = SupplierProduct.objects.select_for_update().filter(source=source, supplier_code=item['code']).first()
        if product and (product.raw_data or {}).get('catalog_revision') == item['revision']:
            return 'unchanged'
        created = product is None
        if created:
            # Reaproveita produto antigo quando a foto exata confirmou a identidade.
            product = SupplierProduct.objects.select_for_update().filter(
                source=source, supplier_code__in=item.get('aliases', [])).order_by('id').first()
            created = product is None
        if product is None:
            product = SupplierProduct(source=source, supplier_code=item['code'])

        previous = (product.raw_data or {}).get('catalog_defaults', {})
        defaults = {
            'name': item['name'], 'brand': item['brand'], 'category': item['category'],
            'description': item['description'], 'suggested_sale_price': Decimal(item['price']),
            'dropshipping_cost': Decimal(item['cost']),
        }
        for field, value in defaults.items():
            # Em revisão futura, não sobrescreve o que o administrador mudou.
            if field not in previous or str(getattr(product, field)) == str(previous[field]):
                setattr(product, field, value)
        product.supplier_code = item['code']
        if created:
            # O fornecedor trabalha sob consulta: a grade deve ser confirmada.
            product.sizes = ''
            product.stock_quantity = 999
            product.status_note = 'Numeração e disponibilidade sob consulta.'
            product.is_active = True
            product.is_visible = True

        storage = SupplierProduct._meta.get_field('image_file').storage
        stored = []
        known_files = dict((product.raw_data or {}).get('catalog_files', {}))
        for photo in item['photos']:
            name = known_files.get(photo['sha256'])
            if not name:
                # O storage Supabase desta loja não permite HEAD/ListObject.
                # Reutilização é controlada no banco, sem consultar o bucket.
                target = f"supplier_products/pdf26/{photo['sha256'][:32]}.jpg"
                name = storage.save(target, ContentFile((path.parent / photo['file']).read_bytes()), max_length=100)
                known_files[photo['sha256']] = name
            stored.append((photo, name))
        # Fotos enviadas pelo catálogo que saíram do manifesto revisado (ex.: foto
        # substituída por versão sem a marca do fornecedor). Fotos manuais não entram aqui.
        current = {photo['sha256'] for photo in item['photos']}
        removed = {known_files.pop(sha) for sha in list(known_files) if sha not in current}
        # A capa atual só muda na primeira importação, se ainda for a anterior ou se saiu do catálogo.
        previous_cover = (product.raw_data or {}).get('catalog_cover')
        if not previous_cover or str(product.image_file) == previous_cover or str(product.image_file) in removed:
            product.image_file = stored[0][1]
        raw = dict(product.raw_data or {})
        raw.update({
            'catalog_revision': item['revision'], 'catalog_id': data['catalog'],
            'catalog_defaults': {k: str(v) for k, v in defaults.items()},
            'catalog_cover': stored[0][1], 'catalog_pages': item['pages'],
            'catalog_quality': item['quality'], 'faixa': item['tier'],
            'catalog_retail': item['retail'], 'availability_confirmed': False,
            'catalog_files': known_files,
        })
        product.raw_data = raw
        product.save()
        if removed:
            SupplierProductPhoto.objects.filter(product=product, image__in=removed).delete()
        for position, (photo, name) in enumerate(stored[1:], 1):
            SupplierProductPhoto.objects.get_or_create(product=product, image=name,
                defaults={'position': position, 'caption': photo.get('color', '')})
        # Só cores confirmadas em fotos individuais são opções de compra.
        colors = set()
        for position, (photo, name) in enumerate(stored):
            if photo.get('color'):
                colors.add(photo['color'])
                variant, made = SupplierProductVariant.objects.get_or_create(product=product, name=photo['color'],
                    defaults={'image': name, 'position': position})
                if not made and str(variant.image) in removed:
                    variant.image = name
                    variant.save(update_fields=['image'])
        if removed:
            # Cor que só existia na foto retirada deixa de ser opção de compra.
            product.variants.filter(image__in=removed).exclude(name__in=colors).delete()
            transaction.on_commit(lambda names=frozenset(removed): self.delete_unused_files(storage, names))
        # Arquiva apenas duplicatas cuja foto foi identificada, preservando pedidos.
        SupplierProduct.objects.filter(source=source, supplier_code__in=item.get('aliases', [])).exclude(
            pk=product.pk).update(is_visible=False, is_active=False)
        return 'created' if created else 'updated'

    def delete_unused_files(self, storage, names):
        # O storage pode sobrescrever pelo mesmo nome: só apaga arquivo que nenhum cadastro usa.
        for name in names:
            if (SupplierProduct.objects.filter(image_file=name).exists()
                    or SupplierProductPhoto.objects.filter(image=name).exists()
                    or SupplierProductVariant.objects.filter(image=name).exists()):
                continue
            try:
                storage.delete(name)
            except Exception as exc:
                self.stderr.write(f'Não foi possível apagar {name} do storage: {exc}')
