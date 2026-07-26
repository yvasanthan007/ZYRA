import ollama

MAX_HISTORY = 10

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

conversation = [
    {
        "role": "system",
        "content": (
            "You are Zyra, a helpful, intelligent, friendly AI assistant. "
            "Answer naturally and briefly unless the user asks for more details. "
            + SECURITY_ANALYST_PERSONA
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
            model="llama3",
            messages=conversation,
            options={
                "temperature": 0.4,
                "num_predict": 100,
            }
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
        return "Sorry, I'm having trouble connecting to the AI model. Please make sure Ollama is running."
    except Exception as e:
        print(f"AI error: {e}")
        return "Sorry, something went wrong. Please try again."