"""
Router — Credits Endpoints

/api/v1/credits — credit balance, purchase, transaction history, and Razorpay webhook.
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel

from core.dependencies import get_current_user
from services.credits import credit_service, CREDIT_PACKS

router = APIRouter()


class CreditPurchaseRequest(BaseModel):
    """Credit pack purchase request."""
    pack_id: str
    payment_id: str
    order_id: str = ""
    signature: str = ""


class OrderCreateRequest(BaseModel):
    """Request to create a Razorpay order."""
    pack_id: str


@router.get("/credits/balance")
async def get_balance(user_id: str = Depends(get_current_user)):
    """Get current user's credit balance and usage stats."""
    return await credit_service.get_balance(user_id)


@router.get("/credits/packs")
async def get_packs():
    """List available credit packs."""
    return {"packs": CREDIT_PACKS}


@router.post("/credits/create-order")
async def create_order(
    req: OrderCreateRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Create a new Razorpay order for a credit pack.
    Returns order details for the frontend to initialize checkout.
    """
    return await credit_service.create_razorpay_order(user_id, req.pack_id)


@router.post("/credits/purchase")
async def purchase_credits(
    req: CreditPurchaseRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Complete a credit pack purchase after Razorpay payment.
    Verifies payment signature and adds credits to user account.
    """
    from core.exceptions import ValidationError

    if req.pack_id not in CREDIT_PACKS:
        raise ValidationError("Invalid pack ID")

    pack = CREDIT_PACKS[req.pack_id]

    # Verify Razorpay payment if signature provided
    if req.signature and req.order_id:
        is_valid = await credit_service.verify_razorpay_payment(
            req.payment_id, req.order_id, req.signature
        )
        if not is_valid:
            raise ValidationError("Payment verification failed")

    # Add credits
    await credit_service.add_credits(
        user_id,
        pack["credits"],
        f"{req.pack_id} pack",
        req.payment_id,
    )

    return {"success": True, "credits_added": pack["credits"]}


@router.post("/credits/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """
    Razorpay webhook for payment events.
    Handles: payment.captured, payment.failed
    
    SECURITY: Verifies webhook signature using HMAC-SHA256 to prevent forged payments.
    Only processes events with valid signatures from Razorpay.
    """
    import json
    import hmac
    import hashlib
    import structlog
    from fastapi import HTTPException
    from config.settings import settings

    logger = structlog.get_logger("equated.webhooks.razorpay")

    # ── Guard: Razorpay must be fully configured ──
    if not settings.razorpay_configured:
        logger.warning("razorpay_webhook_not_configured")
        raise HTTPException(
            status_code=503,
            detail="Payment processing is not configured. Contact support.",
        )

    # Get the raw request body
    body = await request.body()

    # Extract signature from headers
    signature = request.headers.get("X-Razorpay-Signature")
    if not signature:
        logger.warning("razorpay_webhook_missing_signature")
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header")

    # Verify webhook signature using HMAC-SHA256
    expected_signature = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signature, expected_signature):
        logger.warning(
            "razorpay_webhook_invalid_signature",
            provided_sig=signature[:16],
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Signature verified ✓ — safe to process the event
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        logger.error("razorpay_webhook_malformed_json")
        raise HTTPException(status_code=400, detail="Malformed JSON")

    event_type = event.get("event", "")
    logger.info("razorpay_webhook_received", event_type=event_type)

    if event_type == "payment.captured":
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        user_id = notes.get("user_id")
        pack_id = notes.get("pack_id")

        if user_id and pack_id and pack_id in CREDIT_PACKS:
            pack = CREDIT_PACKS[pack_id]
            logger.info(
                "razorpay_payment_processed",
                user_id=user_id[:8],
                pack_id=pack_id,
                credits=pack["credits"],
            )
            await credit_service.add_credits(
                user_id,
                pack["credits"],
                f"{pack_id} pack (webhook)",
                payment.get("id", ""),
            )
        else:
            logger.warning(
                "razorpay_payment_missing_notes",
                has_user_id=bool(user_id),
                has_pack_id=bool(pack_id),
                valid_pack=pack_id in CREDIT_PACKS if pack_id else False,
            )
    elif event_type == "payment.failed":
        logger.warning("razorpay_payment_failed", event=event)

    return {"status": "ok"}


@router.get("/credits/history")
async def get_history(
    user_id: str = Depends(get_current_user),
    limit: int = 20,
):
    """Get credit transaction history."""
    transactions = await credit_service.get_transaction_history(user_id, limit)
    return {"transactions": transactions}
