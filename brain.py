import ollama

MAX_HISTORY = 10

conversation = [
    {
        "role": "system",
        "content": (
            "You are Zyra, a helpful, intelligent, friendly AI assistant. "
            "Answer naturally and briefly unless the user asks for more details."
        )
    }
]


def ask_ai(question):
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

    except Exception:
        return "Sorry, Repeat it again !!."