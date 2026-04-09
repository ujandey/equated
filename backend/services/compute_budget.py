"""
Services — Compute Budget Manager & Weighted Queue

Implements Phase 2 Economic Controls.
1. Computes pessimistic upfront cost for admission.
2. Reserves credits atomically and checks credit-griefing caps.
3. Weighs the request and applies Weighted Fair Queuing (WFQ).
4. Settles the final bill based on EXACT compute seconds.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import structlog

from config.settings import settings
from core.contracts import ASTAnalysis, SandboxResult, Settlement
from core.exceptions import CreditError, NodeCapacityError
from cache.redis_cache import redis_client
from services.credits import credit_service
from db.connection import get_db

logger = structlog.get_logger("equated.services.compute_budget")


class ComputeBudgetManager:
    """
    Manages the 'Reserve -> Execute -> Settle' economic defense flow.
    """

    async def reserve(self, user_id: str, ast: ASTAnalysis, model_name: str) -> str:
        """
        Stage 1: Reserve pessimistic worst-case budget.
        
        1. Calculates estimated worst-case credits (Compute + Model + LLM padding).
        2. Checks max active reservations (anti-griefing).
        3. Atomically deducts from DB (reserves).
        
        Returns reservation_id on success, raises CreditError if unaffordable
        or NodeCapacityError if anti-griefing limits breached.
        """
        # 1. Pessimistic Cost Check
        # Heavy math operations could cost 5x more than light ones
        compute_multiplier = 5 if ast.category == "heavy" else 1
        model_base_cost = self._get_model_cost(model_name)
        
        # Worst case: Max compute cost + premium model cost + padding
        worst_case_cost = (compute_multiplier * settings.WFQ_HEAVY_WEIGHT) + model_base_cost

        # 2. Reservation Concurrency Cap (Anti Griefing R4-1)
        active_key = f"reservations:{user_id}:active"
        active_count = await redis_client.client.scard(active_key)
        
        if active_count >= settings.MAX_ACTIVE_RESERVATIONS_PER_USER:
            logger.warning(
                "reservation_griefing_blocked",
                user_id=user_id,
                active_count=active_count,
            )
            # R4-1 Soft DoS protection - Reject quickly
            raise NodeCapacityError("Too many active heavy requests.", retry_after=5)

        # 3. DB Atomic Reserve
        db = await get_db()
        result = await db.fetchrow(
            """UPDATE users 
               SET credits = credits - $1 
               WHERE id = $2 AND credits >= $1
               RETURNING credits""",
            worst_case_cost, user_id
        )

        if not result:
            actual_credits = await db.fetchval("SELECT credits FROM users WHERE id = $1", user_id) or 0
            if actual_credits < worst_case_cost:
                 raise CreditError(f"Need {worst_case_cost} credits to reserve for this operation. You have {actual_credits}.")
            else:
                 raise CreditError("Reservation failed due to concurrent modification. Please retry.")

        reservation_id = f"res_v1_{uuid.uuid4().hex}"
        
        # 4. Track reservation to prevent zombie locks
        pipe = redis_client.client.pipeline()
        pipe.sadd(active_key, reservation_id)
        pipe.expire(active_key, settings.RESERVATION_TTL_SECONDS)
        # Store metadata for janitor recovery/refunds
        pipe.hset(f"res_meta:{reservation_id}", mapping={
            "user_id": user_id,
            "amount": worst_case_cost,
            "created_at": time.time(),
            "execution_started": 0,
            "last_heartbeat": time.time(),
        })
        pipe.expire(f"res_meta:{reservation_id}", settings.RESERVATION_TTL_SECONDS)
        await pipe.execute()

        await db.execute(
            """INSERT INTO credit_transactions (user_id, amount, type, description)
               VALUES ($1, $2, 'reservation', $3)""",
            user_id, -worst_case_cost, f"Reserved for computation ({reservation_id[:8]})"
        )
        
        return reservation_id

    async def heartbeat(self, reservation_id: str):
        """Update heartbeat to prevent janitor reclamation during long execution."""
        await redis_client.client.hset(
            f"res_meta:{reservation_id}",
            "last_heartbeat",
            time.time()
        )

    async def start_execution(self, reservation_id: str):
        """Mark reservation as executing to avoid idle timeout."""
        await redis_client.client.hset(
            f"res_meta:{reservation_id}",
            "execution_started",
            1
        )
        await self.heartbeat(reservation_id)

    async def settle(self, reservation_id: str, user_id: str,
                     sandbox_res: SandboxResult | None, 
                     model_name: str, has_llm_call: bool) -> Settlement:
        """
        Stage 2: Measure -> Charge -> Refund Remainder
        
        This establishes the EXACT bill based on what was actually consumed.
        Rebates unspent worst-case reserved credits back to user.
        """
        active_key = f"reservations:{user_id}:active"
        meta_key = f"res_meta:{reservation_id}"
        
        raw_meta = await redis_client.client.hgetall(meta_key)
        if not raw_meta:
            logger.error("settlement_missing_reservation", reservation_id=reservation_id)
            # Cannot settle a reservation that doesn't exist (likely Janitor released it)
            return Settlement(
                reservation_id=reservation_id, user_id=user_id,
                reserved_credits=0, actual_compute_cost=0, actual_model_cost=0,
                actual_token_cost=0, final_cost=0, refunded_credits=0,
                compute_seconds=0.0, model_name=model_name, billing_basis="none"
            )

        reserved_amount = int(raw_meta.get("amount", 0))

        # 1. Measure cost authority
        compute_cost = 0
        compute_seconds = 0.0
        if sandbox_res:
            compute_seconds = sandbox_res.compute_seconds
            # Charging Model: e.g. 1 credit per 2 seconds of compute time, min 1 credit if heavy
            compute_cost = max(1, int(compute_seconds * settings.COMPUTE_CREDIT_RATE))

        model_cost = self._get_model_cost(model_name) if has_llm_call else 0
        token_cost = 0 # Future expansion for token counting

        # True multidimensional billing: take the maximum of the cost vectors
        final_cost = max(compute_cost, model_cost, token_cost)
        
        # Ensure we don't charge more than reserved
        final_cost_capped = min(final_cost, reserved_amount)
        refund_amount = reserved_amount - final_cost_capped

        # 2. Apply Refund
        if refund_amount > 0:
            db = await get_db()
            await db.execute(
                "UPDATE users SET credits = credits + $1 WHERE id = $2",
                refund_amount, user_id,
            )
            await db.execute(
                """INSERT INTO credit_transactions (user_id, amount, type, description)
                   VALUES ($1, $2, 'refund', $3)""",
                user_id, refund_amount, f"Refund unused reserve ({reservation_id[:8]})"
            )

        # 3. Determine explicit billing basis (what triggered highest cost factor)
        if final_cost == compute_cost and compute_cost > 0:
            billing_basis = "compute"
        elif final_cost == token_cost and token_cost > 0:
            billing_basis = "tokens"
        else:
            billing_basis = "model"

        # 4. Cleanup reservation state
        pipe = redis_client.client.pipeline()
        pipe.srem(active_key, reservation_id)
        pipe.delete(meta_key)
        await pipe.execute()

        logger.info(
            "budget_settled", 
            reservation=reservation_id[:8],
            user_id=user_id[:8],
            reserved=reserved_amount,
            cost=final_cost_capped,
            refund=refund_amount,
            basis=billing_basis,
            compute_s=round(compute_seconds, 2)
        )

        return Settlement(
            reservation_id=reservation_id,
            user_id=user_id,
            reserved_credits=reserved_amount,
            actual_compute_cost=compute_cost,
            actual_model_cost=model_cost,
            actual_token_cost=token_cost,
            final_cost=final_cost_capped,
            refunded_credits=refund_amount,
            compute_seconds=compute_seconds,
            model_name=model_name,
            billing_basis=billing_basis
        )

    def _get_model_cost(self, model_name: str) -> int:
        from services.credits import MODEL_CREDIT_COSTS
        return MODEL_CREDIT_COSTS.get(model_name, 1)


# Singleton
compute_budget = ComputeBudgetManager()
