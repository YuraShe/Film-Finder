import json
import re
from typing import Any

from openai import OpenAI

from . import config
from .utils import safe_str_list, deduplicate_keep_order

client = OpenAI(
    base_url=config.API_BASE,
    api_key=config.API_KEY,
)

ANALYZER_PROMPT = """
You are a movie-memory analyzer.

Your job is NOT to answer the user directly.

You must analyze ALL user messages in the conversation, not only the last one.

CRITICAL:
- Aggregate clues from the entire user conversation history.
- Use older and newer user messages together if they are compatible.
- Do NOT use assistant messages as evidence.
- If the latest user message is short (for example: "yes", "no", "hello"), still consider previous user messages in the same chat.
- If the user message does NOT contain any movie-related information across the whole user history,
  you MUST set:
    "need_search": false
    "confidence": "low"
    "keywords": []
    and ask clarifying questions.
- NEVER invent plot points, keywords, or movie signals if they are not present.

Return STRICT JSON only.

Schema:
{
  "need_search": true,
  "confidence": "low",
  "content_type": "movie",
  "genre": [],
  "period": [],
  "country_or_language": [],
  "plot_points": [],
  "key_scenes": [],
  "characters_or_actors": [],
  "atmosphere_or_style": [],
  "setting": [],
  "keywords": [],
  "clarifying_questions": []
}
"""


POST_RETRIEVAL_RULES = """
Use the retrieved candidates if they are relevant.

Rules:
1. If confidence is high, provide ONE main answer in STRICT format:
Title: <title>
Year: <year or unknown>
Why it matches: <short explanation>

2. If confidence is medium or low, provide 3-5 likely candidates in this format:
1. Title (year) — why it matches
2. Title (year) — why it matches
...

3. After a candidate list, ask 1-2 short clarifying questions.

4. Do not invent titles.
5. Do not say you searched a vector database unless needed.
6. Do not reveal internal reasoning.
7. Be concise, natural, analytical, and helpful.
"""


NO_RETRIEVAL_RULES = """
There is not enough information for database retrieval yet.

Rules:
1. Ask 1 to 3 short and highly useful clarifying questions.
2. Do not provide a random candidate list if evidence is too weak.
3. Do not reveal internal reasoning.
4. Be friendly and focused.
"""


def extract_json_object(text: str) -> dict:
    if not text:
        raise ValueError("Порожня відповідь від analyzer")

    cleaned = text.strip()

    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"Не вдалося знайти JSON у відповіді analyzer: {text}")

    return json.loads(match.group(0))


def normalize_analysis(data: dict) -> dict:
    normalized = {
        "need_search": bool(data.get("need_search", False)),
        "confidence": str(data.get("confidence", "low")).strip().lower() or "low",
        "content_type": str(data.get("content_type", "unknown")).strip().lower() or "unknown",
        "genre": safe_str_list(data.get("genre")),
        "period": safe_str_list(data.get("period")),
        "country_or_language": safe_str_list(data.get("country_or_language")),
        "plot_points": safe_str_list(data.get("plot_points")),
        "key_scenes": safe_str_list(data.get("key_scenes")),
        "characters_or_actors": safe_str_list(data.get("characters_or_actors")),
        "atmosphere_or_style": safe_str_list(data.get("atmosphere_or_style")),
        "setting": safe_str_list(data.get("setting")),
        "keywords": safe_str_list(data.get("keywords")),
        "clarifying_questions": safe_str_list(data.get("clarifying_questions")),
    }

    merged_keywords = (
        normalized["keywords"]
        + normalized["genre"]
        + normalized["period"]
        + normalized["country_or_language"]
        + normalized["plot_points"]
        + normalized["key_scenes"]
        + normalized["characters_or_actors"]
        + normalized["atmosphere_or_style"]
        + normalized["setting"]
    )

    normalized["keywords"] = deduplicate_keep_order(merged_keywords)

    if normalized["confidence"] not in {"low", "medium", "high"}:
        normalized["confidence"] = "low"

    if len(normalized["clarifying_questions"]) > 3:
        normalized["clarifying_questions"] = normalized["clarifying_questions"][:3]

    return normalized


def analyze_conversation_for_retrieval(history_messages: list[dict]) -> dict:
    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": ANALYZER_PROMPT},
            *history_messages,
        ],
        temperature=0.2,
        max_tokens=500,
        stream=False,
    )

    raw = response.choices[0].message.content if response.choices else ""

    parsed = extract_json_object(raw or "{}")
    normalized = normalize_analysis(parsed)

    print("\n[DEBUG][ANALYZER NORMALIZED]")
    print(json.dumps(normalized, ensure_ascii=False, indent=2))
    print("[/DEBUG]\n")

    return normalized

def should_search_chroma(analysis, history):
    if not analysis.get("need_search"):
        return False

    current_keywords = analysis.get("keywords", [])
    history_keywords = extract_keywords_from_history(history)

    all_keywords = deduplicate_keep_order(
        current_keywords + history_keywords
    )

    confidence = analysis.get("confidence")
    print("Keywords for retrieval:", all_keywords)
    print("Confidence level:", confidence)
    if confidence == "high":
        return True

    if confidence == "medium" and len(all_keywords) >= 5:
        return True

    print("Skipping Chroma search due to low confidence or insufficient keywords.")
    return False

def extract_keywords_from_history(history):
    all_keywords = []

    for msg in history:
        if msg.role != "user":
            continue

        analysis = analyze_conversation_for_retrieval([
            {"role": "user", "content": msg.content}
        ])

        all_keywords.extend(analysis.get("keywords", []))

    return deduplicate_keep_order(all_keywords)

def build_chroma_query(analysis: dict) -> str:
    keywords = safe_str_list(analysis.get("keywords"))
    content_type = str(analysis.get("content_type", "")).strip()

    parts: list[str] = []

    if content_type and content_type != "unknown":
        parts.append(content_type)

    parts.extend(keywords[:12])

    return ", ".join(deduplicate_keep_order(parts))


def format_candidates_for_prompt(candidates: list[dict]) -> str:
    if not candidates:
        return "No candidates found."

    lines = []
    for idx, item in enumerate(candidates, start=1):
        lines.append(
            f"{idx}. "
            f"Title: {item.get('title', 'Unknown')} | "
            f"Year: {item.get('year', 'unknown')} | "
            f"Distance: {item.get('distance', 'unknown')}\n"
            f"Document: {item.get('document', '')}\n"
            f"Metadata: {json.dumps(item.get('metadata', {}), ensure_ascii=False)}"
        )
    return "\n\n".join(lines)


def build_analysis_context(analysis: dict) -> str:
    return json.dumps(analysis, ensure_ascii=False, indent=2)


def build_final_messages(history, analysis: dict, candidates: list[dict]) -> list[dict]:
    from .utils import load_system_prompt

    messages = [{"role": "system", "content": load_system_prompt()}]

    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    if candidates:
        messages.append(
            {
                "role": "system",
                "content": (
                    f"{POST_RETRIEVAL_RULES}\n\n"
                    "Extracted signals:\n"
                    f"{build_analysis_context(analysis)}\n\n"
                    "Retrieved candidates:\n"
                    f"{format_candidates_for_prompt(candidates)}"
                ),
            }
        )
    else:
        messages.append(
            {
                "role": "system",
                "content": (
                    f"{NO_RETRIEVAL_RULES}\n\n"
                    "Extracted signals:\n"
                    f"{build_analysis_context(analysis)}"
                ),
            }
        )

    return messages