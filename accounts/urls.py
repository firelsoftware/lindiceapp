from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("cadastro/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("verificar-telefone/", views.verify_phone, name="verify_phone"),
    path("painel/", views.dashboard, name="dashboard"),
    path("perfil/", views.profile, name="profile"),
    path("senha/", views.change_password, name="change_password"),
    path("medidas/", views.measurements, name="measurements"),
    path("parcelamento/<int:sale_id>/", views.choose_installments, name="choose_installments"),
    path("gestao/", views.management_dashboard, name="management_dashboard"),
    path("gestao/vendas/nova/", views.create_credit_sale, name="create_credit_sale"),
    path("gestao/produtos/", views.product_list, name="product_list"),
    path("gestao/produtos/novo/", views.create_product, name="create_product"),
    path("gestao/produtos/<int:product_id>/", views.product_detail, name="product_detail"),
    path("gestao/produtos/<int:product_id>/custos/novo/", views.add_product_cost, name="add_product_cost"),
    path("gestao/relatorios/lucro/", views.profit_report, name="profit_report"),
    path("preview/marca/", views.brand_preview, name="brand_preview"),
]
