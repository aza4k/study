import json
import os
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

ANDROID_PACKAGE_NAME = os.getenv('GOOGLE_PLAY_PACKAGE_NAME', 'com.fundev.uz')
ANDROID_PUBLISHER_SCOPE = 'https://www.googleapis.com/auth/androidpublisher'
BASE_PUBLISHER_URL = 'https://androidpublisher.googleapis.com/androidpublisher/v3/applications'

PLAY_ONE_TIME_PRODUCTS = {
    'energy_50': Decimal('50.00'),
    'energy_180': Decimal('180.00'),
    'energy_500': Decimal('500.00'),
}

PLAY_SUBSCRIPTIONS = {
    'studyai_pro_monthly': ('pro', False),
    'studyai_pro_annual': ('pro', True),
    'studyai_ultra_monthly': ('ultra', False),
    'studyai_ultra_annual': ('ultra', True),
}

SUBSCRIPTION_ENERGY_REWARDS = {
    'pro': Decimal('150.00'),
    'ultra': Decimal('500.00'),
}


class BillingConfigError(Exception):
    pass


class BillingVerificationError(Exception):
    pass


def _get_authorized_session() -> AuthorizedSession:
    raw_or_path = (os.getenv('GOOGLE_PLAY_SERVICE_ACCOUNT_JSON') or '').strip()
    if not raw_or_path:
        raise BillingConfigError(
            "Google Play Service Account JSON serverda sozlanmagan (GOOGLE_PLAY_SERVICE_ACCOUNT_JSON)."
        )

    if raw_or_path.startswith('{'):
        info = json.loads(raw_or_path)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[ANDROID_PUBLISHER_SCOPE]
        )
    else:
        if not os.path.exists(raw_or_path):
            raise BillingConfigError("Service account JSON fayli topilmadi.")
        creds = service_account.Credentials.from_service_account_file(
            raw_or_path, scopes=[ANDROID_PUBLISHER_SCOPE]
        )
    return AuthorizedSession(creds)


def _extract_expiry_datetime(data: dict, is_annual: bool = False):
    line_items = data.get('lineItems') or []
    for item in line_items:
        raw_exp = item.get('expiryTime')
        if raw_exp:
            dt = parse_datetime(str(raw_exp))
            if dt is not None:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.utc)
                return dt
    return timezone.now() + timedelta(days=366 if is_annual else 31)


def verify_google_play_purchase(product_id: str, purchase_token: str) -> dict:
    """
    Verify a Google Play product or subscription purchaseToken using Google Play Android Publisher API v3.
    Automatically acknowledges unacknowledged purchases so Google does not auto-refund after 3 days.
    """
    if product_id not in PLAY_ONE_TIME_PRODUCTS and product_id not in PLAY_SUBSCRIPTIONS:
        raise BillingVerificationError(f"Noma'lum mahsulot ID: {product_id}")

    session = _get_authorized_session()

    if product_id in PLAY_ONE_TIME_PRODUCTS:
        url = f"{BASE_PUBLISHER_URL}/{ANDROID_PACKAGE_NAME}/purchases/products/{product_id}/tokens/{purchase_token}"
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            raise BillingVerificationError(f"Google Play tekshiruvi xatosi ({resp.status_code}): {resp.text[:250]}")

        data = resp.json()
        if data.get('purchaseState') != 0:
            raise BillingVerificationError("Xarid hali yakunlanmagan yoki bekor qilingan.")

        if data.get('acknowledgementState') == 0:
            session.post(f"{url}:acknowledge", json={}, timeout=10)

        return {
            'purchase_type': 'one_time',
            'order_id': data.get('orderId', ''),
            'expires_at': None,
            'raw': data,
        }

    # Subscription verification (Play Billing v2 endpoint)
    v2_url = f"{BASE_PUBLISHER_URL}/{ANDROID_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{purchase_token}"
    resp = session.get(v2_url, timeout=15)
    if resp.status_code != 200:
        raise BillingVerificationError(f"Obuna tekshiruvi xatosi ({resp.status_code}): {resp.text[:250]}")

    data = resp.json()
    sub_state = data.get('subscriptionState', '')
    if sub_state not in ('SUBSCRIPTION_STATE_ACTIVE', 'SUBSCRIPTION_STATE_IN_GRACE_PERIOD'):
        raise BillingVerificationError(f"Obuna faol emas (holat: {sub_state}).")

    if data.get('acknowledgementState') != 'ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED':
        ack_url = f"{BASE_PUBLISHER_URL}/{ANDROID_PACKAGE_NAME}/purchases/subscriptions/{product_id}/tokens/{purchase_token}:acknowledge"
        session.post(ack_url, json={}, timeout=10)

    _, is_annual = PLAY_SUBSCRIPTIONS[product_id]
    expires_at = _extract_expiry_datetime(data, is_annual=is_annual)

    return {
        'purchase_type': 'subscription',
        'order_id': data.get('latestOrderId', ''),
        'expires_at': expires_at,
        'subscription_state': sub_state,
        'raw': data,
    }


def sync_user_subscription_status(user) -> bool:
    """
    Reconciles a user's active PRO/ULTRA subscription when `subscription_expires_at` passes.
    If Google Play auto-renewed the subscription, extends expiry and credits monthly bonus energy.
    If expired/canceled/on-hold, downgrades user cleanly back to 'free'.
    Returns True if user fields were updated.
    """
    from core.models import PlayPurchase

    if getattr(user, 'subscription_type', 'free') not in ('pro', 'ultra'):
        return False

    expires_at = getattr(user, 'subscription_expires_at', None)
    if not expires_at or timezone.now() <= expires_at:
        return False

    token = (getattr(user, 'play_purchase_token', '') or '').strip()
    product_id = (getattr(user, 'last_play_product_id', '') or '').strip()

    if token and product_id in PLAY_SUBSCRIPTIONS:
        try:
            verified = verify_google_play_purchase(product_id, token)
            new_exp = verified.get('expires_at')
            if new_exp and new_exp > timezone.now():
                plan, is_annual = PLAY_SUBSCRIPTIONS[product_id]
                latest_order = verified.get('order_id', '')
                known_orders = set(
                    PlayPurchase.objects.filter(user=user).values_list('order_id', flat=True)
                )
                user.subscription_type = plan
                user.is_annual = is_annual
                user.subscription_expires_at = new_exp
                update_fields = ['subscription_type', 'is_annual', 'subscription_expires_at']
                if latest_order and latest_order not in known_orders:
                    grant = SUBSCRIPTION_ENERGY_REWARDS.get(plan, Decimal('150.00'))
                    user.energy = Decimal(str(user.energy)) + grant
                    update_fields.append('energy')
                    PlayPurchase.objects.create(
                        user=user,
                        product_id=product_id,
                        purchase_token=f"{token}:renew:{latest_order}"[:512],
                        order_id=latest_order,
                        purchase_type='subscription',
                        verified=True,
                        raw_response=verified.get('raw') or {},
                    )
                user.save(update_fields=update_fields)
                cache.delete(f"courses_list_v2_{user.id}")
                cache.delete('api_leaderboard_cache')
                return True
        except BillingVerificationError:
            # Expired, canceled, paused, or revoked in Google Play -> downgrade below
            pass
        except Exception:
            # Transient network/API error: keep current plan temporarily instead of premature downgrade
            return False

    user.subscription_type = 'free'
    user.is_annual = False
    user.subscription_expires_at = None
    user.save(update_fields=['subscription_type', 'is_annual', 'subscription_expires_at'])
    cache.delete(f"courses_list_v2_{user.id}")
    cache.delete('api_leaderboard_cache')
    return True
