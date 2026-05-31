import json
import urllib.error
import urllib.request

from django.conf import settings


MERCADO_PAGO_API = "https://api.mercadopago.com"


class MercadoPagoNotConfigured(Exception):
    pass


class MercadoPagoRequestError(Exception):
    pass


def site_url(request):
    if settings.PUBLIC_SITE_URL:
        return settings.PUBLIC_SITE_URL.rstrip("/")

    return request.build_absolute_uri("/").rstrip("/")


def is_test_environment():
    return settings.MERCADO_PAGO_ACCESS_TOKEN.startswith("TEST-")


def mercado_pago_request(path, payload=None, method="POST"):
    if not settings.MERCADO_PAGO_ACCESS_TOKEN:
        raise MercadoPagoNotConfigured("Configure MERCADO_PAGO_ACCESS_TOKEN para ativar pagamentos.")

    data = None
    headers = {
        "Authorization": f"Bearer {settings.MERCADO_PAGO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        f"{MERCADO_PAGO_API}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise MercadoPagoRequestError(f"Mercado Pago retornou erro {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise MercadoPagoRequestError(f"Nao foi possivel acessar Mercado Pago: {exc}") from exc


def create_checkout_preference(order, request):
    base_url = site_url(request)
    payload = {
        "items": [
            {
                "title": order.product_name,
                "quantity": order.quantity,
                "currency_id": "BRL",
                "unit_price": float(order.unit_price),
            }
        ],
        "external_reference": order.order_code,
        "back_urls": {
            "success": f"{base_url}/loja/pagamento/sucesso/",
            "failure": f"{base_url}/loja/pagamento/falha/",
            "pending": f"{base_url}/loja/pagamento/pendente/",
        },
        "notification_url": f"{base_url}/loja/mercado-pago/webhook/",
        "auto_return": "approved",
    }

    if not is_test_environment():
        payload["payer"] = {
            "name": order.customer_name,
            "email": order.customer_email,
            "phone": {"number": order.customer_phone},
        }

    response = mercado_pago_request("/checkout/preferences", payload)

    return {
        "id": response.get("id", ""),
        "init_point": response.get("init_point") or response.get("sandbox_init_point", ""),
    }


def create_credit_sale_card_preference(sale, request):
    base_url = site_url(request)
    payload = {
        "items": [
            {
                "title": sale.description,
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(sale.selected_total_with_interest),
            }
        ],
        "external_reference": f"credit-sale:{sale.id}",
        "back_urls": {
            "success": f"{base_url}/pagamento/mercado-pago/sucesso/",
            "failure": f"{base_url}/pagamento/mercado-pago/falha/",
            "pending": f"{base_url}/pagamento/mercado-pago/pendente/",
        },
        "notification_url": f"{base_url}/loja/mercado-pago/webhook/",
        "auto_return": "approved",
        "payment_methods": {
            "excluded_payment_types": [
                {"id": "ticket"},
                {"id": "bank_transfer"},
                {"id": "atm"},
                {"id": "debit_card"},
            ],
            "installments": sale.selected_installments,
        },
    }

    if not is_test_environment():
        payload["payer"] = {
            "name": sale.client.full_name,
            "email": sale.client.email,
            "phone": {"number": sale.client.profile.phone},
        }

    response = mercado_pago_request("/checkout/preferences", payload)

    return {
        "id": response.get("id", ""),
        "init_point": response.get("init_point") or response.get("sandbox_init_point", ""),
    }


def get_payment(payment_id):
    return mercado_pago_request(f"/v1/payments/{payment_id}", method="GET")
