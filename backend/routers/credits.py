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
    """
    import json
    body = await request.body()
    event = json.loads(body)

    event_type = event.get("event", "")

    if event_type == "payment.captured":
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        user_id = notes.get("user_id")
        pack_id = notes.get("pack_id")

        if user_id and pack_id and pack_id in CREDIT_PACKS:
            pack = CREDIT_PACKS[pack_id]
            await credit_service.add_credits(
                user_id,
                pack["credits"],
                f"{pack_id} pack (webhook)",
                payment.get("id", ""),
            )

    return {"status": "ok"}


@router.get("/credits/history")
async def get_history(
    user_id: str = Depends(get_current_user),
    limit: int = 20,
):
    """Get credit transaction history."""
    transactions = await credit_service.get_transaction_history(user_id, limit)
    return {"transactions": transactions}
