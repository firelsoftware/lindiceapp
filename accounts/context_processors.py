from .notifications import generate_due_notifications


def notifications(request):
    if not request.user.is_authenticated:
        return {}

    generate_due_notifications()

    return {
        "notification_unread_count": request.user.notifications.filter(read_at__isnull=True).count(),
    }


def store_cart(request):
    cart = request.session.get("store_cart", {})
    item_count = sum(int(item.get("quantity", 1)) for item in cart.values())

    return {
        "store_cart_item_count": item_count,
    }
