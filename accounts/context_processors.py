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
    return {
        "google_analytics_id": settings.GOOGLE_ANALYTICS_ID,
    }


def user_extras(request):
    if not request.user.is_authenticated:
        return {}

    profile = getattr(request.user, "profile", None)

    if not profile:
        return {}

    extra_data = profile.extra_data or {}
    sales_keyword = (extra_data.get("sales_report_brand_keyword") or "").strip()
    sales_title = (extra_data.get("sales_report_title") or "Relatorio de vendas").strip()
    theme = extra_data.get("brand_theme") or {}

    return {
        "user_sales_report_enabled": bool(sales_keyword),
        "user_sales_report_label": sales_title,
        "user_brand_theme": theme if isinstance(theme, dict) else {},
    }
