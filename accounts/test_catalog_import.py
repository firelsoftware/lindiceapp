import copy
import hashlib
import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.catalog_pricing import pdf_catalog_price
from accounts.management.commands.importar_catalogos_revisados import ROOT, read_manifest
from accounts.models import SupplierProduct, SupplierProductPhoto, SupplierProductVariant


class CatalogPriceTests(SimpleTestCase):
    def test_margin_threshold_and_rounding_up(self):
        for base, expected in [('139.90','159.90'),('159.90','179.90'),('189.90','209.90'),
                               ('199.90','219.90'),('200','229.90'),('200.01','219.90'),
                               ('209.90','229.90'),('499.90','529.90')]:
            with self.subTest(base=base):
                result = pdf_catalog_price(base)
                self.assertEqual(result, Decimal(expected))
                factor = Decimal('1.05') if Decimal(base)>200 else Decimal('1.10')
                self.assertGreaterEqual(result, Decimal(base)*factor)
                self.assertLess(result-Decimal(base)*factor, 10)

    def test_invalid_prices_are_rejected(self):
        for value in ('0','-1','NaN','Infinity'):
            with self.assertRaises(ValueError): pdf_catalog_price(value)

    def test_all_shipped_manifests_and_photos_validate(self):
        for path in ROOT.glob('*/manifest.json'):
            self.assertGreater(len(read_manifest(path)['products']), 0)


class CatalogImportTests(TestCase):
    def setUp(self):
        self.initial_count = SupplierProduct.objects.count()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = self.root/'tenis'
        self.catalog.mkdir()
        self.settings = override_settings(MEDIA_ROOT=str(self.root/'media'))
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.root_patch = patch('accounts.management.commands.importar_catalogos_revisados.ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        photos=[]
        for name,color in [('a.jpg','Preto'),('b.jpg','Branco')]:
            content=name.encode()
            (self.catalog/name).write_bytes(content)
            photos.append({'file':name,'sha256':hashlib.sha256(content).hexdigest(),'color':color})
        self.item={'code':'pdf26-test','name':'Tênis teste — Premium','brand':'Teste','category':'Tênis Premium',
                   'description':'Sob consulta.','retail':'159.90','price':'179.90','cost':'111.93',
                   'tier':20,'quality':'Premium','pages':[4],'photos':photos,'revision':'v1','aliases':['antigo']}
        self.manifest={'catalog':'teste','products':[self.item],'pending':[]}
        self.save_manifest()

    def save_manifest(self):
        (self.catalog/'manifest.json').write_text(json.dumps(self.manifest),encoding='utf8')

    def test_shared_legacy_alias_is_rejected_before_import(self):
        other = copy.deepcopy(self.item)
        other['code'] = 'pdf26-other-model'
        self.manifest['products'].append(other)
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, 'Equivalência antiga ambígua'):
            self.run_import()
        self.assertEqual(SupplierProduct.objects.count(), self.initial_count)

    def run_import(self, **kwargs):
        call_command('importar_catalogos_revisados', stdout=StringIO(), **kwargs)

    def test_rerun_preserves_admin_changes_and_gallery_without_new_uploads(self):
        self.run_import()
        product=SupplierProduct.objects.get(supplier_code=self.item['code'])
        self.assertEqual(len(product.gallery_images()),2)
        self.assertEqual(product.variants.count(),2)
        product.name='Nome corrigido pela loja'
        product.suggested_sale_price=Decimal('199.90')
        product.is_visible=False
        product.save()
        files=list((self.root/'media').rglob('*.jpg'))
        self.run_import()
        product.refresh_from_db()
        self.assertEqual(product.name,'Nome corrigido pela loja')
        self.assertEqual(product.suggested_sale_price,Decimal('199.90'))
        self.assertFalse(product.is_visible)
        self.assertEqual(list((self.root/'media').rglob('*.jpg')),files)
        self.assertEqual(SupplierProductPhoto.objects.count(),1)
        self.assertEqual(SupplierProductVariant.objects.count(),2)
        self.assertEqual(product.payment_options()['card']['total'],Decimal('199.90'))

    def test_known_old_product_reused_other_supplier_untouched(self):
        old=SupplierProduct.objects.create(source='parceiro_sob_consulta',supplier_code='antigo',name='Antigo')
        other=SupplierProduct.objects.create(source='wearzone',supplier_code='antigo',name='Outro',suggested_sale_price=500)
        self.run_import()
        old.refresh_from_db();other.refresh_from_db()
        self.assertEqual(old.supplier_code,self.item['code'])
        self.assertEqual(old.suggested_sale_price,Decimal('179.90'))
        self.assertEqual(other.name,'Outro')
        self.assertEqual(other.suggested_sale_price,Decimal('500'))

    def test_bad_photo_prevents_all_database_writes(self):
        (self.catalog/'b.jpg').write_bytes(b'changed')
        with self.assertRaises(CommandError):self.run_import()
        self.assertEqual(SupplierProduct.objects.count(),self.initial_count)

    def test_dry_run_never_writes(self):
        self.run_import(ensaio=True)
        self.assertEqual(SupplierProduct.objects.count(),self.initial_count)
        self.assertFalse((self.root/'media').exists())

    def test_new_revision_keeps_manual_price_and_reuses_uploads(self):
        self.run_import()
        product=SupplierProduct.objects.get(supplier_code=self.item['code'])
        product.suggested_sale_price=Decimal('199.90');product.save()
        self.item['revision']='v2';self.item['description']='Descrição revisada.';self.save_manifest()
        self.run_import()
        product.refresh_from_db()
        self.assertEqual(product.description,'Descrição revisada.')
        self.assertEqual(product.suggested_sale_price,Decimal('199.90'))
        self.assertEqual(len(list((self.root/'media').rglob('*.jpg'))),2)
