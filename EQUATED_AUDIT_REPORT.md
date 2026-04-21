# Equated Platform: Comprehensive Brutal Audit

> **WARNING:** This is a ruthless, system-level audit. It prioritizes ground reality over theoretical designs. Assume everything mentioned here directly impacts the survival of the product.

## 1. PROJECT UNDERSTANDING

*   **What is this product?** A multi-engine AI platform designed for STEM education, routing user queries to the most cost-effective/capable LLMs while offloading mathematical computation to a deterministic symbolic engine (SymPy).
*   **What problem does it solve?** LLMs are terrible at deterministic math, often hallucinating numbers or skipping steps. Human tutors are too expensive. Equated aims to provide highly accurate, step-by-step tutoring at near-zero marginal cost.
*   **Who is it for?** High school and engineering students studying mathematics, physics, and chemistry.
*   **Intended Core Features:** Multi-model routing (DeepSeek, Groq, Mistral), Semantic Vector Caching, Image OCR + LaTeX parsing, deterministic symbolic solving, and structured pedagogical explanations.
*   **End-to-End Data Flow:** Frontend (Next.js) receives query (text/image) → API Gateway (FastAPI) → 5-Gate Economic Defense / Rate Limiting → Problem Parser / Intent Classifier → Symbolic Math Parser → SymPy Sandbox Execution → LLM Explanation Generation → Response Assembly → Frontend.

## 2. CURRENT IMPLEMENTATION (GROUND REALITY)

### The Codebase Reality
The codebase is heavily lopsided. It features an incredibly complex, military-grade backend API, paired with a skeletal, visually appealing but functionally shallow frontend. 

**Backend (FastAPI)**
*   **Controllers/Services:** The backend is deeply integrated. The `master_controller` was recently decoupled into `intent_classifier.py`, `query_splitter.py`, and `response_assembler.py`.
*   **Business Logic:** High completion on AI routing (`ai/router.py`) and SymPy integration (`math_engine.py`, `sympy_sandbox.py`).
*   **Defenses:** You have implemented `kill_storm_tracker.py`, `ast_guard.py`, `local_governor.py`, `weighted_queue.py`, and `compute_budget.py`. This is **Phase 3 Adversarial Intelligence** implemented before Phase 1 user onboarding is complete.
*   **Hidden Debt:** The sheer synchronous depth of a single `/solve` request. A request passes through 5 security/capacity gates before it even reaches the LLM or SymPy layer.

**Frontend (Next.js)**
*   **What UI exists?** A brutalist landing page (`page.tsx`) and the scaffolding for a chat interface (`chat/page.tsx`). 
*   **What actually works?** Visuals. The frontend is currently a shell. The Next.js setup is standard, but state management (Zustand/Redux), actual API hookups to the complex backend WebSockets/SSE, and LaTeX rendering (KaTeX) lack necessary completion or robustness.

**AI System**
*   **Components:** `HybridMathParser` (uses heuristics + LLMs to build SymPy payloads), `AdaptiveExplainer` (for pedagogical output), `ModelRouter` (excellent capability/cost routing).
*   **Controllability:** High. You successfully isolated computation to SymPy, ensuring LLMs only handle the "English" explanation, not the "Math". This is a highly deterministic and scalable approach. 

**Database / State**
*   **Schema Quality:** The `db/schema.py` is comprehensive (Users, Sessions, TopicBlocks, UserTopicMastery, CacheEntry with pgvector). 
*   **Reality:** While the schema is mature, the actual usage of complex features like `UserTopicMastery` (assumed levels, learning velocity) is weakly integrated into the main request pipeline.

---

## 3. WHAT WORKS VS WHAT DOESN'T

| Feature | Status | Why it works / doesn't | Prod Readiness |
| :--- | :---: | :--- | :--- |
| **Model Routing** | 🟢 Working | `ai/router.py` correctly handles cost/complexity matrices natively. | Ready |
| **SymPy Engine** | 🟢 Working | Isolated execution via `sympy_sandbox.py` securely limits rogue computations. | Ready |
| **Adversarial Defenses** | 🟡 Partially | Over-engineered. `kill_storm_tracker` and `wfq` work but will likely misfire and drop legitimate user queries under mild latency. | Demo Only |
| **Hybrid Math Parser** | 🟡 Partially | Relies heavily on Regex and LLM strict JSON formatting. Edge case queries will break the parser pipeline. | Beta |
| **OCR / Image Parsing** | 🟡 Partially | `parser.py` integrates Tesseract/pix2tex, but handling file uploads via Next.js to FastAPI directly is historically brittle. | Alpha |
| **Frontend UI / UX** | 🔴 Broken | Landing page is gorgeous, but the actual app lacks deep component wiring, KaTeX rendering, and file upload UX. | Prototype |
| **Payments / Credits** | 🔴 Missing | Database models exist (`CreditTransaction`), but Razorpay webhooks and full lifecycle are incomplete. | Missing |

---

## 4. GAP ANALYSIS

**CURRENT STATE vs IDEAL FINAL PRODUCT**

*   **What is missing?** The connective tissue. The frontend cannot gracefully handle the complexity of the backend's SSE streaming, error states (e.g., AST Rejections, Queue Full), and complex LaTeX rendering simultaneously. 
*   **What is incorrectly implemented?** The request pipeline. You are running stochastic validators, AST guards, and compute budget settlements inline with the `/solve` HTTP request. This invites timeout issues.
*   **What is overengineered?** The Economic Defense system. You are protecting a fortress that has no treasure. Features like Weighted Fair Queuing (WFQ) and Kill-Storm tracking are for systems doing 10k RPS.
*   **What is underbuilt?** The actual student experience. Where is the hint-based learning UI? Where is the mistake detection visualization? 

### Gap Classification
**Critical (Blocks Product):** Frontend-to-Backend integration. Auth. Rendering LaTeX/Markdown flawlessly in the chat UI.  
**Important (Affects Quality):** Tuning the HybridMathParser to handle weirdly formatted high-school equations without crashing.  
**Optional (Nice to have):** WFQ concurrency limits, Kill-Storm network tracking, Sub-cent cost routing optimizations.  

---

## 5. ARCHITECTURAL FLAWS

1.  **Synchronous Monolithic Pipeline:** In `routers/solver.py`, a single request must acquire a local governor lock, pass an AST guard, acquire a WFQ lock, reserve a DB compute budget, execute the model, and settle the budget. **Bottleneck:** A single slow DB query or Redis latency spike will cause cascading failures and 503s across the board.
2.  **SymPy Cold Starts:** The PRD mentions SymPy running as a microservice on Render. If SymPy is doing heavily insulated sandboxing locally inside FastAPI, concurrency will CPU-throttle your main web workers immediately.
3.  **Strict JSON LLM Parsing:** `HybridMathParser` begs an LLM to "Output ONLY valid JSON". Even with `gpt-4o-mini`, this will occasionally fail and return markdown-fenced JSON or truncated output, tanking the solve request.

---

## 6. PRODUCT READINESS

**Verdict: Alpha / Engineering Prototype.**

If deployed today, it would break immediately upon user interaction because:
1. The frontend lacks the deep React state management to funnel inputs and render the highly-structured `ControllerResponse` payloads.
2. The `solver.py` endpoint will brutally reject normal students who trigger the `AST_Guard` or `Kill_Storm_Tracker` due to minor anomalies or double-clicks.
3. The UX for displaying mathematical steps, fallbacks, and "understanding" is not implemented on the client.

---

## 7. DISTANCE TO FINAL PRODUCT

**Realistic Completion: 45%**

*Major Milestones Remaining:*
1. Complete Frontend UI/UX (Chat, Math Rendering, File Upload).
2. End-to-End integration of Auth and Credit System.
3. Infrastructure Deployment (Vercel + Render + Supabase) and CORS/Environment stabilization.
4. User Acceptance Testing (UAT) with *actual* messy student math queries.

---

## 8. ACTIONABLE ROADMAP

### Phase 1: Stabilization (Immediate)
*   **Task 1:** Bypass or mock the extreme economic defenses (`kill_storm_tracker`, `wfq`) in non-production environments. They are masking core logic bugs.
*   **Task 2:** Write 50 functional integration tests passing real high-school math strings into the `master_controller` to ensure the `HybridMathParser` doesn't choke.

### Phase 2: Core Completion (Frontend Focus)
*   **Task 1:** Build the Chat UI. Implement React Markdown + KaTeX to securely and beautifully render the backend's step-by-step payloads.
*   **Task 2:** Wire up Supabase Auth. A user must be able to log in, get a session ID, and see their previous topic blocks.
*   **Task 3:** Implement the Image Upload pipeline (Client → Supabase Storage → FastAPI OCR). 

### Phase 3: Polish & UX
*   **Task 1:** Simplify the `solver.py` endpoint. De-risk the 5-gate pipeline so timeouts don't destroy the UX.
*   **Task 2:** Implement the Payments/Credits UI.

---

## 9. HARSH TRUTHS

**What you are doing wrong:** You are acting like a site reliability engineer for a global enterprise before you have a single successful user onboarding. 

**What you are underestimating:** How incredibly messy, unstructured, and unpredictable student inputs are. Your AST guards and Strict JSON parsers will reject 40% of legitimate queries because a 15-year-old typed `solve x2-5   x+6=0 pls`. 

**What will fail if you continue like this:** You will build the most secure, cost-optimized, military-grade architecture in the world for an application that nobody uses because the frontend is too shallow and the backend is too strict. 

**The Fix:** Stop building defenses. Start building the user experience. You need a frictionless textbox that spits out beautiful math, no matter how badly the user typed it. Stop optimizing for massive-scale adversarial hackers; start optimizing for learning students.
