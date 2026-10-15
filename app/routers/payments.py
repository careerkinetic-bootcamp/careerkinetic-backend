import json
from datetime import datetime, timezone
from typing import Annotated

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.domain import PaymentOrder, User


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)

# =============================================================================
# 1. Master Server-Side Price Catalog (Anti-Tampering)
# Never trust the frontend client to set prices!
# =============================================================================
COHORT_CATALOG = {
    "aiml": {
        "title": "AI & Machine Learning Cohort",
        "plans": {
            "full": {"name": "Full Tuition", "amount": 49999},
            "monthly": {"name": "Monthly Installment (1st Month)", "amount": 6999},
        },
    },
    "swe": {
        "title": "Software Engineering (SWE) Cohort",
        "plans": {
            "full": {"name": "Full Tuition", "amount": 39999},
            "monthly": {"name": "Monthly Installment (1st Month)", "amount": 5499},
        },
    },
}


def resolve_cohort_pricing(cohort_id: str, plan_type: str) -> tuple[str, str, int]:
    cohort_key = cohort_id.strip().lower()
    cohort = COHORT_CATALOG.get(cohort_key)
    if not cohort:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown cohort '{cohort_id}'. Valid options: {list(COHORT_CATALOG.keys())}",
        )

    plan_key = "monthly" if "month" in plan_type.lower() else "full"
    plan = cohort["plans"].get(plan_key)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan type '{plan_type}'.",
        )

    return cohort["title"], plan["name"], plan["amount"]


def get_razorpay_client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Razorpay credentials are not configured in backend settings.",
        )
    return razorpay.Client(
        auth=(
            settings.razorpay_key_id,
            settings.razorpay_key_secret,
        )
    )


# =============================================================================
# 2. Schemas
# =============================================================================
class CreateOrderRequest(BaseModel):
    cohort_id: str = Field(..., description="Cohort ID, e.g. 'aiml' or 'swe'")
    plan_type: str = Field(
        default="full", description="Plan type: 'full' or 'monthly'"
    )


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# =============================================================================
# 3. Create Order (Authenticated + Server-Calculated Price + DB Persistence)
# =============================================================================
@router.post("/create-order")
async def create_order(
    order_req: CreateOrderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    title, plan_name, official_amount = resolve_cohort_pricing(
        order_req.cohort_id, order_req.plan_type
    )

    try:
        client = get_razorpay_client()
        amount_in_paise = official_amount * 100
        timestamp = int(datetime.now(timezone.utc).timestamp())
        receipt_id = f"ck_{order_req.cohort_id[:4]}_{timestamp}"

        # 1. Create order on Razorpay servers
        order_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": receipt_id,
            "payment_capture": 1,
            "notes": {
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "cohort_id": order_req.cohort_id,
                "cohort_title": title,
                "plan_type": order_req.plan_type,
            },
        }
        order = client.order.create(data=order_data)

        # 2. Save new transaction into local database as PENDING
        db_order = PaymentOrder(
            user_id=current_user.id,
            user_email=current_user.email,
            cohort_id=order_req.cohort_id.lower(),
            cohort_title=title,
            plan_type=order_req.plan_type,
            amount=official_amount,
            currency="INR",
            status="PENDING",
            razorpay_order_id=order["id"],
        )
        db.add(db_order)
        await db.commit()
        await db.refresh(db_order)

        return {
            "success": True,
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": settings.razorpay_key_id,
            "cohort_title": title,
            "amount_rupees": official_amount,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Razorpay order creation failed: {str(exc)}",
        )


# =============================================================================
# 4. Atomic Order Fulfillment Engine (Enterprise ACID & Concurrency Safe)
# =============================================================================
async def fulfill_order_atomic(
    db: AsyncSession,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str | None = None,
    payment_method: str | None = None,
) -> tuple[bool, PaymentOrder | None, bool]:
    """
    Executes an atomic, concurrency-safe fulfillment of a payment order.

    Guarantees:
    1. Row-Level Locking (SELECT ... FOR UPDATE): Prevents concurrent race conditions
       between the frontend callback and Razorpay webhook.
    2. Idempotency: If the order was already fulfilled, safely exits without re-processing.
    3. ACID Transaction: Updates both the payment_orders table and users table atomically.

    Returns:
        (success: bool, order_record: PaymentOrder | None, already_paid: bool)
    """
    # 1. Acquire exclusive row-level lock on the order row in PostgreSQL
    stmt = (
        select(PaymentOrder)
        .where(PaymentOrder.razorpay_order_id == razorpay_order_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    order_record = result.scalar_one_or_none()

    if not order_record:
        return False, None, False

    # 2. Idempotency Guard: if already PAID, exit early cleanly
    if order_record.status == "PAID":
        return True, order_record, True

    # 3. Update Order state
    order_record.status = "PAID"
    order_record.razorpay_payment_id = razorpay_payment_id
    if razorpay_signature:
        order_record.razorpay_signature = razorpay_signature
    if payment_method:
        order_record.payment_method = payment_method
    order_record.updated_at = datetime.now(timezone.utc)
    db.add(order_record)

    # 4. Acquire exclusive lock on the User record and activate enrollment
    user_stmt = (
        select(User)
        .where(User.id == order_record.user_id)
        .with_for_update()
    )
    user = (await db.execute(user_stmt)).scalar_one_or_none()
    if user:
        current_profile = dict(user.profile_data or {})
        enrolled_cohorts = list(current_profile.get("enrolled_cohorts", []))
        if order_record.cohort_id not in enrolled_cohorts:
            enrolled_cohorts.append(order_record.cohort_id)
            current_profile["enrolled_cohorts"] = enrolled_cohorts
            user.profile_data = current_profile
            flag_modified(user, "profile_data")
            db.add(user)

    # 5. Commit all changes atomically
    await db.commit()
    await db.refresh(order_record)
    return True, order_record, False


# =============================================================================
# 5. Verify Payment (Cryptographic Signature + Atomic Fulfillment)
# =============================================================================
@router.post("/verify-payment")
async def verify_payment(
    payment: VerifyPaymentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # 1. Cryptographically verify signature using HMAC-SHA256
    client = get_razorpay_client()
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": payment.razorpay_order_id,
                "razorpay_payment_id": payment.razorpay_payment_id,
                "razorpay_signature": payment.razorpay_signature,
            }
        )
    except razorpay.errors.SignatureVerificationError:
        # Mark order as FAILED in database under row lock
        stmt = (
            select(PaymentOrder)
            .where(PaymentOrder.razorpay_order_id == payment.razorpay_order_id)
            .with_for_update()
        )
        res = await db.execute(stmt)
        order_rec = res.scalar_one_or_none()
        if order_rec and order_rec.status != "PAID":
            order_rec.status = "FAILED"
            order_rec.updated_at = datetime.now(timezone.utc)
            db.add(order_rec)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment verification failed: Invalid Razorpay signature.",
        )

    # 2. Detect payment method from Razorpay API (upi, card, emi, netbanking)
    payment_method = None
    try:
        payment_details = client.payment.fetch(payment.razorpay_payment_id)
        payment_method = payment_details.get("method")
    except Exception:
        pass  # Graceful fallback if Razorpay API lookup encounters transient error

    # 3. Atomically fulfill the order and grant access
    success, order_record, already_paid = await fulfill_order_atomic(
        db=db,
        razorpay_order_id=payment.razorpay_order_id,
        razorpay_payment_id=payment.razorpay_payment_id,
        razorpay_signature=payment.razorpay_signature,
        payment_method=payment_method,
    )

    if not success or not order_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found in database records.",
        )

    return {
        "success": True,
        "message": (
            "Payment was already verified successfully."
            if already_paid
            else "Payment verified and enrollment activated!"
        ),
        "order_id": order_record.razorpay_order_id,
        "payment_id": order_record.razorpay_payment_id,
        "cohort_id": order_record.cohort_id,
        "payment_method": order_record.payment_method,
    }


# =============================================================================
# 6. Webhook Listener (Safety Net for Network Drops or Closed Tabs)
# =============================================================================
@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    # 1. Verify webhook signature if secret configured
    if settings.razorpay_webhook_secret and signature:
        try:
            client = get_razorpay_client()
            client.utility.verify_webhook_signature(
                body.decode("utf-8"),
                signature,
                settings.razorpay_webhook_secret,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Webhook signature verification failed: {str(e)}",
            )

    try:
        event_data = json.loads(body)
    except Exception:
        return JSONResponse(status_code=200, content={"status": "ignored_non_json"})

    event_type = event_data.get("event")

    # 2. Handle payment capture event asynchronously
    if event_type in ["payment.captured", "order.paid"]:
        payload_data = event_data.get("payload", {})
        payment_entity = payload_data.get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id")
        payment_id = payment_entity.get("id")
        method = payment_entity.get("method")

        if order_id and payment_id:
            await fulfill_order_atomic(
                db=db,
                razorpay_order_id=order_id,
                razorpay_payment_id=payment_id,
                payment_method=method,
            )

    return {"status": "ok"}