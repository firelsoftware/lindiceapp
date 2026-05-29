from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("loja/", views.store_front, name="store_front"),
    path("loja/produto/<int:product_id>/", views.store_product_detail, name="store_product_detail"),
    path("loja/produto/<int:product_id>/comprar/", views.store_checkout, name="store_checkout"),
    path("loja/pedido/<str:order_code>/", views.store_order_detail, name="store_order_detail"),
    path("loja/pagamento/sucesso/", views.payment_success, name="payment_success"),
    path("loja/pagamento/falha/", views.payment_failure, name="payment_failure"),
    path("loja/pagamento/pendente/", views.payment_pending, name="payment_pending"),
    path("loja/mercado-pago/webhook/", views.mercado_pago_webhook, name="mercado_pago_webhook"),
    path("cadastro/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html", redirect_authenticated_user=True), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("verificar-telefone/", views.verify_phone, name="verify_phone"),
    path("painel/", views.dashboard, name="dashboard"),
    path("minha-conta/", views.account, name="account"),
    path("perfil/", views.profile, name="profile"),
    path("senha/", views.change_password, name="change_password"),
    path("medidas/", views.measurements, name="measurements"),
    path("parcelamento/<int:sale_id>/", views.choose_installments, name="choose_installments"),
    path("gestao/", views.management_dashboard, name="management_dashboard"),
    path("gestao/cadastros/<int:profile_id>/", views.review_client_profile, name="review_client_profile"),
    path("gestao/vendas/nova/", views.create_credit_sale, name="create_credit_sale"),
    path("gestao/loja/pedidos/", views.store_orders, name="store_orders"),
    path("gestao/loja/pedidos/<str:order_code>/", views.store_order_admin, name="store_order_admin"),
    path("gestao/produtos/", views.product_list, name="product_list"),
    path("gestao/fornecedor/produtos/", views.supplier_products, name="supplier_products"),
    path("gestao/fornecedor/importar/", views.import_supplier_products, name="import_supplier_products"),
    path("gestao/produtos/novo/", views.create_product, name="create_product"),
    path("gestao/produtos/<int:product_id>/", views.product_detail, name="product_detail"),
    path("gestao/produtos/<int:product_id>/custos/novo/", views.add_product_cost, name="add_product_cost"),
    path("gestao/relatorios/lucro/", views.profit_report, name="profit_report"),
    path("preview/marca/", views.brand_preview, name="brand_preview"),
]
