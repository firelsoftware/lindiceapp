from urllib.parse import quote

from django.conf import settings

from .notifications import generate_due_notifications


def notifications(request):
    if not request.user.is_authenticated:
        return {}

    generate_due_notifications()

    return {
        "notification_unread_count": request.user.notifications.filter(read_at__isnull=True).count(),
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
    }


def store_cart(request):
    cart = request.session.get("store_cart", {})
    item_count = sum(int(item.get("quantity", 1)) for item in cart.values())

    return {
        "store_cart_item_count": item_count,
    }


def site_analytics(request):
    whatsapp = "".join(ch for ch in getattr(settings, "STORE_WHATSAPP_NUMBER", "") if ch.isdigit())
    firelsoft_whatsapp = "".join(ch for ch in getattr(settings, "FIRELSOFT_WHATSAPP_NUMBER", "") if ch.isdigit())

    # Numero em formato de leitura: 5561995135066 -> (61) 99513-5066
    legivel = ""

    if len(whatsapp) >= 12:
        ddd, numero = whatsapp[2:4], whatsapp[4:]
        legivel = f"({ddd}) {numero[:5]}-{numero[5:]}"

    instagram = getattr(settings, "STORE_INSTAGRAM_URL", "")
    perfil = instagram.rstrip("/").rsplit("/", 1)[-1].split("?")[0] if instagram else ""

    return {
        "google_analytics_id": settings.GOOGLE_ANALYTICS_ID,
        "store_whatsapp_url": f"https://wa.me/{whatsapp}" if whatsapp else "",
        "store_whatsapp_label": legivel,
        "store_instagram_url": instagram,
        "store_instagram_handle": f"@{perfil}" if perfil else "",
        "firelsoft_whatsapp_url": (
            f"https://wa.me/{firelsoft_whatsapp}?text={quote('Olá! Vim pelo app da Lindice e queria tirar uma dúvida.')}"
            if firelsoft_whatsapp
            else ""
        ),
    }


def user_extras(request):
    if not request.user.is_authenticated:
        return {}

    user_doces_e_mais_enabled = request.user.email.lower() == "andrezamartinssantossilva@gmail.com" or request.user.is_staff

    profile = getattr(request.user, "profile", None)

    if not profile:
        return {"user_doces_e_mais_enabled": user_doces_e_mais_enabled}

    extra_data = profile.extra_data or {}
    sales_keyword = (extra_data.get("sales_report_brand_keyword") or "").strip()
    sales_title = (extra_data.get("sales_report_title") or "Relatorio de vendas").strip()
    theme = extra_data.get("brand_theme") or {}

    return {
        "user_sales_report_enabled": bool(sales_keyword),
        "user_sales_report_label": sales_title,
        "user_brand_theme": theme if isinstance(theme, dict) else {},
        "user_doces_e_mais_enabled": user_doces_e_mais_enabled,
    }
