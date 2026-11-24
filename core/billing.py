import json
import os
from decimal import Decimal

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
        # purchaseState: 0 = Purchased, 1 = Canceled, 2 = Pending
        if data.get('purchaseState') != 0:
            raise BillingVerificationError("Xarid hali yakunlanmagan yoki bekor qilingan.")

        if data.get('acknowledgementState') == 0:
            session.post(f"{url}:acknowledge", json={}, timeout=10)

        return {
            'purchase_type': 'one_time',
            'order_id': data.get('orderId', ''),
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

    return {
        'purchase_type': 'subscription',
        'order_id': data.get('latestOrderId', ''),
        'raw': data,
    }
