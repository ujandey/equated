"""
Router — Solver Endpoint

Main solve endpoint: /api/v1/solve
Orchestrates the full pipeline:
  Parse → Cache Check → Classify → Route → Math → Verify → Explain → Respond
"""

from fastapi import APIRouter, Request, HTTPException

from db.models import SolveRequest, SolveResponse
from services.parser import problem_parser
from services.query_normalizer import query_normalizer
from services.rate_limiter import user_rate_limiter
from services.streaming import streaming_handler
from services.session_manager import session_manager
from services.explanation import explanation_generator
from services.verification import verification_engine
from cache.query_cache import query_cache
from ai.classifier import classifier
from ai.router import model_router
from ai.fallback import fallback_handler
from ai.prompts import SOLVER_SYSTEM_PROMPT
from ai.prompt_optimizer import prompt_optimizer
from ai.cost_optimizer import cost_optimizer
from config.settings import settings
from config.feature_flags import flags

router = APIRouter()


@router.post("/solve", response_model=SolveResponse)
async def solve_problem(req: SolveRequest, request: Request):
    """
    Solve a STEM problem with the full pipeline.

    Flow:
      1. Rate limit / credit check
      2. Parse & normalize input
      3. Check cache (Redis → pgvector)
      4. Classify problem
      5. Route to model
      6. Execute (with fallback)
      7. Math engine verification
      8. Generate structured explanation
      9. Store in cache
      10. Return response
    """
    user_id = request.state.user_id

    # 1. Rate limit / credit check
    limit_result = await user_rate_limiter.check_and_deduct(user_id)
    if not limit_result["allowed"]:
        raise HTTPException(status_code=429, detail=limit_result["message"])

    # 2. Parse input (decode image if provided)
    image_bytes = None
    if req.image_base64:
        import base64
        try:
            image_bytes = base64.b64decode(req.image_base64)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid base64 image data")

        # Enforce max image size
        max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
        if len(image_bytes) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Image too large ({len(image_bytes) // (1024*1024)}MB). Max: {settings.MAX_IMAGE_SIZE_MB}MB.",
            )

    parsed = problem_parser.parse(
        text=req.question,
        image_bytes=image_bytes,
        input_type=req.input_type,
    )

    # 3. Check cache
    cache_result = await query_cache.lookup(parsed.normalized_text)
    if cache_result.found:
        return SolveResponse(
            final_answer=cache_result.cached_solution.get("solution", ""),
            cached=True,
            credits_remaining=limit_result["remaining"],
        )

    # 3.5 Check duplicates (AI Deduplication Lock)
    import asyncio
    import hashlib
    import structlog
    from cache.redis_cache import redis_client
    
    logger = structlog.get_logger("equated.routers.solver")
    query_hash = hashlib.sha256(parsed.normalized_text.encode()).hexdigest()
    lock_key = f"solve:lock:{query_hash}"
    
    has_lock = await redis_client.set_nx(lock_key, "1", ttl=60)
    
    if not has_lock:
        logger.info("dedup_wait", query_hash=query_hash[:8])
        for _ in range(30):
            await asyncio.sleep(1)
            # check cache again
            cache_result = await query_cache.lookup(parsed.normalized_text)
            if cache_result.found:
                logger.info("dedup_success", query_hash=query_hash[:8])
                return SolveResponse(
                    final_answer=cache_result.cached_solution.get("solution", ""),
                    cached=True,
                    credits_remaining=limit_result["remaining"],
                )
            if not await redis_client.exists(lock_key):
                has_lock = await redis_client.set_nx(lock_key, "1", ttl=60)
                if has_lock:
                    break
        
        if not has_lock:
            logger.warning("dedup_timeout", query_hash=query_hash[:8])

    try:
        # 4. Classify
        classification = classifier.classify(parsed.normalized_text)

        # 5. Route
        decision = model_router.route(classification)

        # 6. Build messages and optimize
        messages = [
            {"role": "system", "content": SOLVER_SYSTEM_PROMPT},
            {"role": "user", "content": parsed.normalized_text},
        ]

        # Add session context if follow-up
        if req.session_id:
            context = await session_manager.get_context_messages(req.session_id)
            messages = [messages[0]] + context + [messages[-1]]

        if flags.streaming_responses and req.stream:
            # Streaming response
            from ai.models import get_model
            model = get_model(decision.provider.value)
            stream = model.stream(messages, decision.max_tokens, decision.temperature)
            
            async def caching_stream_wrapper(original_stream):
                full_text = ""
                try:
                    async for token in original_stream:
                        full_text += token
                        yield token
                finally:
                    # Store in cache and session when stream finishes
                    import asyncio
                    model_val = getattr(decision, "provider", "").value if hasattr(decision, "provider") else "unknown"
                    asyncio.create_task(query_cache.store(parsed.normalized_text, {
                        "solution": full_text,
                        "model": model_val,
                    }))
                    if req.session_id:
                        asyncio.create_task(session_manager.add_message(req.session_id, "user", req.question))
                        asyncio.create_task(session_manager.add_message(req.session_id, "assistant", full_text))
                    
                    if has_lock:
                        await redis_client.delete(lock_key)

            return streaming_handler.create_sse_response(caching_stream_wrapper(stream))

        # Optimize prompts
        messages = prompt_optimizer.optimize(messages)

        # 7. Execute with fallback
        result = await fallback_handler.generate_with_fallback(messages, decision, user_id)
        if not result:
            raise HTTPException(status_code=503, detail="All AI models unavailable")

        # 8. Generate explanation
        explanation = explanation_generator.generate(result.content, req.question)

        # 9. Record usage
        cost_optimizer.record_call(
            provider=decision.provider.value,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.total_cost_usd,
            latency_ms=0.0,
        )

        # 10. Store in cache (background)
        await query_cache.store(parsed.normalized_text, {
            "solution": result.content,
            "model": result.model,
        })

        # Store message in session
        if req.session_id:
            await session_manager.add_message(req.session_id, "user", req.question)
            await session_manager.add_message(req.session_id, "assistant", result.content)

        return SolveResponse(
            problem_interpretation=explanation.problem_interpretation,
            concept_used=explanation.concept_used,
            steps=explanation.steps,
            final_answer=explanation.final_answer,
            quick_summary=explanation.quick_summary,
            alternative_method=explanation.alternative_method,
            common_mistakes=explanation.common_mistakes,
            model_used=decision.provider.value,
            cached=False,
            credits_remaining=limit_result["remaining"],
        )
    finally:
        # If streaming, lock is deleted in wrapper. Otherwise, delete here.
        if has_lock and not (flags.streaming_responses and req.stream):
            await redis_client.delete(lock_key)
