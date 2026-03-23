# AI Model Router — Routing Logic

## Pipeline

```
Query → Classifier → Router → Model → Response
```

## Classification Categories

| Category | Examples |
|----------|---------|
| `math` | Equations, calculus, algebra, matrices |
| `physics` | Forces, circuits, thermodynamics, waves |
| `chemistry` | Reactions, equilibrium, pH, moles |
| `engineering` | Structures, signals, control systems |
| `coding` | Algorithms, data structures, code debugging |
| `reasoning` | Proofs, logical arguments, derivations |
| `general` | Definitions, explanations, concepts |
| `image` | Photographed homework, scanned documents |

## Routing Rules

```
if classified as "math only" (pure computation):
    → SymPy engine (FREE, guaranteed correct)

if complexity == LOW:
    → Groq / Llama 3.3 70B (FREE, sub-200ms)

if complexity == MEDIUM:
    → DeepSeek V3 (~$0.001 per call)

if complexity == HIGH:
    → DeepSeek R1 (~$0.004 per call)

if image input:
    → DeepSeek V3 with vision
```

## Fallback Chain

```
SymPy → Groq → DeepSeek V3 → DeepSeek R1 → Error
```

## Cost Optimization

1. **Cache first** — check Redis (exact) then pgvector (semantic) before ANY model call
2. **Cheapest model first** — always try free tier before paid
3. **Prompt compression** — reduce tokens by 20-40% before sending
4. **Token budgets** — cap output tokens by default, expand on demand
5. **Background embedding** — don't block response on cache storage
