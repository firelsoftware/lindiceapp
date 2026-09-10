"""O que os buscadores leem antes de entrar na loja.

Sem sitemap, o Google descobre produto tropecando em link. Com ele, a loja
entrega a lista pronta - e como o catalogo passa de mil itens, isso e a
diferenca entre ter as fichas indexadas e nao ter.

Sem robots.txt, o buscador tambem gasta tempo em tela de gestao e de cliente,
que nao deveria nem visitar.
"""

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone


def endereco_publico(request, caminho=None):
    """O endereco desta pagina no dominio que a loja escolheu mostrar.

    O site atende em mais de um dominio. Sem escolher um, o buscador trata cada
    um como uma copia do site inteiro e divide a forca entre eles. Com a escolha
    em branco, vale o dominio por onde a visita chegou.
    """
    caminho = request.get_full_path() if caminho is None else caminho

    # Boa parte das fotos do catalogo mora no site do fornecedor: o endereco ja
    # vem completo e nao tem dominio nosso para pendurar na frente.
    if caminho.startswith(("http://", "https://", "//")):
        return caminho

    if settings.SITE_CANONICO:
        return f"{settings.SITE_CANONICO}{caminho}"

    return request.build_absolute_uri(caminho)


# Caminhos que buscador nenhum tem o que fazer: area da loja, area do cliente,
# carrinho e checkout. Nao e segredo - a protecao de verdade e o login -, e so
# para o robo nao gastar visita onde nao ha nada para indexar.
FORA_DA_BUSCA = (
    "/gestao/",
    "/admin/",
    "/painel/",
    "/cadastro/",
    "/entrar/",
    "/loja/carrinho/",
    "/loja/finalizar/",
    "/parcelamento/",
    "/contrato/",
)

# O arquivo que o Search Console pede para provar que o site e da loja. O nome
# vem dele e o conteudo e o proprio nome. Nao e segredo: fica publico no ar de
# qualquer jeito, e nao serve para ninguem que nao mande neste dominio. Mas nao
# pode sumir - o dia que esse endereco parar de responder, a propriedade perde
# a verificacao. Por isso mora no codigo, e nao numa variavel de ambiente que
# alguem pode apagar sem saber o que era.
ARQUIVO_DO_GOOGLE = "google985abea835c787a9.html"


def verificacao_do_google(request):
    return HttpResponse(
        f"google-site-verification: {ARQUIVO_DO_GOOGLE}\n", content_type="text/html"
    )


# Quantos produtos entram no sitemap. O Google aceita 50 mil por arquivo, mas
# gerar mil linhas ja e uma consulta grande num servidor gratuito.
LIMITE_DE_PRODUTOS = 2000


def robots(request):
    linhas = ["User-agent: *"]
    linhas += [f"Disallow: {caminho}" for caminho in FORA_DA_BUSCA]
    linhas.append("")
    linhas.append(f"Sitemap: {endereco_publico(request, reverse('sitemap'))}")

    return HttpResponse("\n".join(linhas) + "\n", content_type="text/plain")


def _url(endereco, alterado_em, prioridade, frequencia):
    quando = alterado_em.date().isoformat() if alterado_em else timezone.localdate().isoformat()

    return (
        "  <url>\n"
        f"    <loc>{endereco}</loc>\n"
        f"    <lastmod>{quando}</lastmod>\n"
        f"    <changefreq>{frequencia}</changefreq>\n"
        f"    <priority>{prioridade}</priority>\n"
        "  </url>"
    )


def sitemap(request):
    from .models import SupplierProduct

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        _url(endereco_publico(request, reverse("home")), None, "1.0", "daily"),
        _url(endereco_publico(request, reverse("store_front")), None, "0.9", "daily"),
    ]

    a_venda = (
        SupplierProduct.objects.filter(is_active=True, is_visible=True, stock_quantity__gt=0)
        .only("id", "updated_at", "category")
        .order_by("-updated_at")
    )

    # Uma entrada por categoria que tem produto: e por elas que a busca costuma
    # chegar ("bota feminina", "tenis premium").
    for categoria in sorted({p.category for p in a_venda if p.category}):
        endereco = endereco_publico(request, f"{reverse('store_front')}?categoria={categoria}")
        partes.append(_url(endereco.replace(" ", "%20"), None, "0.8", "weekly"))

    for produto in a_venda[:LIMITE_DE_PRODUTOS]:
        endereco = endereco_publico(
            request, reverse("store_product_detail", args=[produto.id])
        )
        partes.append(_url(endereco, produto.updated_at, "0.7", "weekly"))

    partes.append("</urlset>")

    return HttpResponse("\n".join(partes), content_type="application/xml")
