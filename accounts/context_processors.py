from .notifications import generate_due_notifications


def notifications(request):
    if not request.user.is_authenticated:
        return {}

    generate_due_notifications()

    return {
        "notification_unread_count": request.user.notifications.filter(read_at__isnull=True).count(),
    }
