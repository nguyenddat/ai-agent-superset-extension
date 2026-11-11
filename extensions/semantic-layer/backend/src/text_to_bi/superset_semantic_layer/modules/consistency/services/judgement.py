import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from ....core.config import settings
from .detection import Candidate, Finding

logger = logging.getLogger(__name__)

# Pairs per model call, and per check: a check stays within one round of parallel calls, and the rest of a large
# glossary is judged by the next check.
PAIRS_PER_CALL = 6
PAIRS_PER_CHECK = 24
MAX_EXPLANATION_LENGTH = 600
UNAVAILABLE_MESSAGE = "Chưa cấu hình OPENROUTER_API_KEY nên chưa kiểm tra được mâu thuẫn về nghĩa giữa các định nghĩa."
FAILED_MESSAGE = "Không gọi được mô hình AI; các cặp chưa kiểm tra sẽ được kiểm tra ở lần sau."
PENDING_MESSAGE = "Còn {count} cặp chưa được AI kiểm tra; bấm “Kiểm tra lại” để tiếp tục."
FALLBACK_EXPLANATION = "AI đánh giá hai nội dung này mâu thuẫn nhau."

# What the model is asked about each kind of pair.
KIND_QUESTIONS = {
    "term_term_meaning": "Hai định nghĩa thuật ngữ có trái nhau không?",
    "term_metric_meaning": "Công thức của metric có tính đúng điều định nghĩa thuật ngữ nói không?",
    "rule_term_meaning": "Rule (điều kiện, ngoại lệ, câu hỏi mẫu) có trái định nghĩa của thuật ngữ nó gắn không?",
    "rule_rule_meaning": "Ngoại lệ hoặc câu hỏi mẫu của rule này có phủ định điều kiện hay kết quả của rule kia không?",
}

SYSTEM_PROMPT = """
Bạn kiểm tra nội dung quản trị của một semantic layer: thuật ngữ nghiệp vụ, metric và expert rule mà AI Agent đọc để
trả lời câu hỏi về dữ liệu. Mỗi cặp có pair_id, câu hỏi cần trả lời và hai mục.

Trả contradiction = true chỉ khi hai mục không thể cùng đúng, hoặc khiến AI Agent hiểu cùng một khái niệm theo hai cách
khác nhau: ngưỡng hay điều kiện trái nhau, định nghĩa phủ định nhau, công thức tính một đại lượng khác điều định nghĩa
nói, ngoại lệ phủ định điều kiện của rule kia, câu hỏi mẫu trái với điều kiện.

Không phải mâu thuẫn: một mục cụ thể hơn hoặc là một mức độ của mục kia; hai khái niệm khác nhau cùng dùng một cột hay
một metric; một mục là đại lượng còn mục kia là điều kiện trên đại lượng đó; một mục thiếu thông tin. Chỉ dựa vào nội
dung được đưa, không suy đoán; khi không chắc, trả contradiction = false.

Với mỗi pair_id trả contradiction và explanation: khi mâu thuẫn, một câu tiếng Việt ngắn (tối đa 40 từ) chỉ ra chỗ
trái nhau cụ thể; khi không mâu thuẫn, để trống.
"""


class PairVerdict(BaseModel):
    pair_id: str = Field(description="pair_id của cặp, giữ nguyên như đầu vào.")
    contradiction: bool = Field(description="true khi hai mục mâu thuẫn nhau.")
    explanation: str = Field(default="", description="Chỗ mâu thuẫn, một câu tiếng Việt ngắn; trống nếu không có.")


class PairVerdicts(BaseModel):
    verdicts: list[PairVerdict] = Field(description="Một kết luận cho mỗi cặp được gửi vào.")


@dataclass(frozen=True)
class Verdict:
    contradiction: bool
    explanation: str


@dataclass(frozen=True)
class SemanticOutcome:
    """How the AI part of a check went: `checked`, `pending` (more pairs left), `unavailable` (no key), `failed`,
    or `deferred` (a rule-only check left the pairs for the AI step that follows it)."""

    status: str
    unchecked: int = 0
    message: str | None = None


# Judges a batch of candidates; returns a verdict for each fingerprint it answered.
Judge = Callable[[list[Candidate]], dict[str, Verdict]]


def judge_request(candidates: list[Candidate]) -> str:
    """The message sent to the model: each pair with its question and both items, numbered by position."""
    pairs = [
        {"pair_id": str(index), "cau_hoi": KIND_QUESTIONS[candidate.kind], "muc_1": candidate.texts[0],
         "muc_2": candidate.texts[1]}
        for index, candidate in enumerate(candidates)
    ]
    return json.dumps(pairs, ensure_ascii=False, indent=2)


def parse_verdicts(raw: Any, candidates: list[Candidate]) -> dict[str, Verdict]:
    """The model's answer by candidate fingerprint; a pair it skipped or answered malformed is left out to retry."""
    if raw is None:
        return {}
    try:
        answer = raw if isinstance(raw, PairVerdicts) else PairVerdicts.model_validate(raw)
    except ValueError:
        logger.warning("The contradiction model answered in an unexpected shape.")
        return {}
    verdicts = {}
    for verdict in answer.verdicts:
        index = verdict.pair_id.strip()
        if not index.isdigit() or int(index) >= len(candidates):
            continue
        explanation = " ".join(verdict.explanation.split())[:MAX_EXPLANATION_LENGTH]
        if verdict.contradiction and not explanation:
            explanation = FALLBACK_EXPLANATION
        verdicts[candidates[int(index)].fingerprint] = Verdict(verdict.contradiction, explanation)
    return verdicts


@lru_cache(maxsize=1)
def _verdict_agent():
    from langchain.agents import create_agent

    from ...data_dictionary.autofill.chat_models import get_chat_model

    return create_agent(
        model=get_chat_model(),
        name="contradiction-judge",
        tools=[],
        response_format=PairVerdicts,
        system_prompt=SYSTEM_PROMPT,
    )


def model_judge(candidates: list[Candidate]) -> dict[str, Verdict]:
    """Ask the OpenRouter chat model the Data Dictionary's AutoFill uses about one batch of pairs."""
    from langchain_core.messages import HumanMessage

    result = _verdict_agent().invoke({"messages": [HumanMessage(content=judge_request(candidates))]})
    return parse_verdicts(result.get("structured_response") if isinstance(result, dict) else None, candidates)


def semantic_judge() -> Judge | None:
    """The model judge, or None when no OpenRouter key is configured."""
    return model_judge if settings.OPENROUTER_API_KEY else None


def _judged_safely(judge: Judge) -> Callable[[list[Candidate]], dict[str, Verdict] | None]:
    def judged(batch: list[Candidate]) -> dict[str, Verdict] | None:
        try:
            return judge(batch)
        # A failing model, whatever the error, must not fail the rule-based checks.
        except Exception:
            logger.exception("The contradiction model could not judge %s pairs.", len(batch))
            return None

    return judged


def judge_candidates(
    candidates: list[Candidate], cached: dict[str, Verdict], judge: Judge | None, defer: bool = False
) -> tuple[dict[str, Verdict], dict[str, Verdict], SemanticOutcome]:
    """The verdicts for the candidates: cached ones as they are, the rest asked of the model in parallel batches.

    Returns every verdict known now, the new ones to cache, and how the AI part went. Without a judge, or when it
    fails, the rule-based findings still stand and the pairs left are judged by a later check. With `defer`, nothing
    is asked: the caller shows the rule-based findings first and asks the model in a second check.
    """
    fingerprints = [candidate.fingerprint for candidate in candidates]
    known = {fingerprint: cached[fingerprint] for fingerprint in fingerprints if fingerprint in cached}
    pending = [candidate for candidate in candidates if candidate.fingerprint not in cached]
    if not pending:
        return known, {}, SemanticOutcome("checked")
    if judge is None:
        return known, {}, SemanticOutcome("unavailable", len(pending), UNAVAILABLE_MESSAGE)
    if defer:
        return known, {}, SemanticOutcome("deferred", len(pending))
    selected = pending[:PAIRS_PER_CHECK]
    batches = [selected[start:start + PAIRS_PER_CALL] for start in range(0, len(selected), PAIRS_PER_CALL)]
    fresh: dict[str, Verdict] = {}
    failed = False
    with ThreadPoolExecutor(max_workers=len(batches)) as pool:
        for answer in pool.map(_judged_safely(judge), batches):
            if answer is None:
                failed = True
            else:
                fresh.update(answer)
    unchecked = len(pending) - len(fresh)
    if failed and not fresh:
        outcome = SemanticOutcome("failed", unchecked, FAILED_MESSAGE)
    elif unchecked:
        outcome = SemanticOutcome("pending", unchecked, PENDING_MESSAGE.format(count=unchecked))
    else:
        outcome = SemanticOutcome("checked")
    return {**known, **fresh}, fresh, outcome


def semantic_findings(candidates: list[Candidate], verdicts: dict[str, Verdict]) -> list[Finding]:
    """A finding for each candidate the model judged contradictory; its explanation is the model's."""
    findings = []
    for candidate in candidates:
        verdict = verdicts.get(candidate.fingerprint)
        if verdict is not None and verdict.contradiction:
            items, fingerprint = candidate.items, candidate.fingerprint
            findings.append(Finding(candidate.kind, items, fingerprint, candidate.texts, verdict.explanation))
    return findings
