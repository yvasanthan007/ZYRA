import os

import ollama

MAX_HISTORY = 10

# ── Model selection (target chat response time: 5–10s) ──
# Benchmarked on this machine with ZYRA's real prompts (warm model):
#   llama3:latest  ~2 tok/s   → 20-40s replies (too slow for chat)
#   phi3:latest    ~4.8 tok/s → ~5-10s typical replies  ← default
#   tinyllama      ~10 tok/s  → fastest, but noticeably weaker answers
# Override without touching code, e.g. for max quality:
#   set ZYRA_OLLAMA_MODEL=llama3:latest   (slower replies)
#   or pull another model:  ollama pull phi3:latest
OLLAMA_MODEL = os.environ.get("ZYRA_OLLAMA_MODEL", "phi3:latest")

# Keep the model loaded between chats — reloading from disk after idle
# costs ~30s (that alone can make a reply feel "broken"). "8760h" (1 year)
# keeps the model resident ~permanently (~3.9 GB RAM for phi3) so every
# reply stays fast. NOTE: this Ollama build rejects keep_alive="-1"
# (400: missing unit in duration) — always use a duration WITH a unit,
# e.g. "24h" to free RAM daily, "5m" to mimic the default.
OLLAMA_KEEP_ALIVE = os.environ.get("ZYRA_OLLAMA_KEEP_ALIVE", "8760h")

# Cap on generated tokens: bounds the worst-case reply time on CPU.
# phi3 at ~4.8 tok/s (100% CPU — no GPU on this machine) →
# worst case ≈ 40/4.8 ≈ 8-10s, typical brief answers 3-7s.
MAX_REPLY_TOKENS = int(os.environ.get("ZYRA_OLLAMA_NUM_PREDICT", "40"))


# ── Backend Security Analysis Module: persona injection ──
# Zyra's system instructions now declare that link inspection is a backend-only
# text task. Whenever the user provides a link or says "Analyse the link" /
# "Analyze this URL", the structured report is produced by the backend security
# engine and returned directly — never fabricated by the LLM, and never
# reflected in the frontend dashboard UI.
try:
    from backend.link_security import SECURITY_ANALYST_PERSONA
except Exception:  # pragma: no cover - fallback if backend package not importable
    SECURITY_ANALYST_PERSONA = (
        "SECURITY ANALYSIS MODE: link inspection is handled by Zyra's backend "
        "security engine and returned as a text-only report. Do not fabricate "
        "analyses or touch the frontend dashboard UI for them."
    )

# ── Network Security Analysis Module: Nmap integration ──
# Zyra can perform network scanning using Nmap for security assessments.
# When the user asks to scan a network or check for vulnerabilities, Zyra
# uses Nmap to discover hosts, scan ports, detect services, and identify
# potential security issues. This is a real security tool, not simulated.
try:
    from nmap_handler import NMAP_PERSONA
except Exception:
    NMAP_PERSONA = (
        "NETWORK SECURITY MODE: Zyra can perform network scanning using Nmap. "
        "When asked to scan networks or check for vulnerabilities, Zyra uses "
        "real Nmap scans to discover hosts, open ports, services, and security issues."
    )

conversation = [
    {
        "role": "system",
        "content": (
            "You are Zyra, a helpful, intelligent, friendly AI assistant. "
            "Answer naturally and briefly unless the user asks for more details. "
            "IMPORTANT: keep every answer very short — at most 2-3 short "
            "sentences (or a few bullet points). Never write paragraphs or "
            "essays unless the user explicitly asks for a detailed answer. "
            + SECURITY_ANALYST_PERSONA
            + " "
            + NMAP_PERSONA
        )
    }
]


def ask_ai(question):
    """Ask the AI a question and get a response."""
    if not question or not question.strip():
        return "Please say something!"
    
    conversation.append(
        {
            "role": "user",
            "content": question
        }
    )

    # Keep only recent conversation
    if len(conversation) > MAX_HISTORY + 1:
        conversation[:] = [conversation[0]] + conversation[-MAX_HISTORY:]

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=conversation,
            options={
                "temperature": 0.4,
                "num_predict": MAX_REPLY_TOKENS,
            },
            keep_alive=OLLAMA_KEEP_ALIVE,
        )

        answer = response["message"]["content"].strip()

        conversation.append(
            {
                "role": "assistant",
                "content": answer
            }
        )

        return answer

    except ollama.ResponseError as e:
        print(f"Ollama error: {e}")
        if "not found" in str(e).lower() or "404" in str(e):
            return (f"The AI model '{OLLAMA_MODEL}' is not installed. "
                    f"Run: ollama pull {OLLAMA_MODEL} "
                    f"(or set ZYRA_OLLAMA_MODEL to an installed model).")
        return "Sorry, I'm having trouble connecting to the AI model. Please make sure Ollama is running."
    except Exception as e:
        print(f"AI error: {e}")
        return "Sorry, something went wrong. Please try again."