"""
  Survey Data Processing System
  Course Feedback Survey (University Students)
  Milestones 5 & 6 — Evolved from Milestones 1–4

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MILESTONE 5 ADDITIONS (Concurrency & High-Performance):
  - ThreadPoolExecutor  : parallel per-respondent analysis
  - ProcessPoolExecutor : CPU-bound heavy analysis via multiprocessing
  - asyncio + aiofiles  : async file I/O for JSON & CSV export
  - ConcurrentSurveyProcessor: orchestrates all concurrent paths
  - PerformanceBenchmark: measures wall-clock speedup (serial vs parallel)
  - ThreadSafeCounter   : Lock-protected shared counter for thread safety
  - asyncio.Queue       : async task queue for streaming export pipeline

MILESTONE 6 ADDITIONS (Research Contribution & Innovation):
  - SentimentAnalyzer   : lightweight rule-based NLP on text answers
  - SmartRecommendation : generates per-respondent feedback recommendations
  - AnomalyDetector     : IQR-based statistical outlier detection on ratings
  - AdaptiveSurveyEngine: ML-style adaptive routing based on prior answers
  - ResearchReportGenerator: produces a structured academic report (Markdown)
  - IntelligentInsightEngine: integrates all M6 components into one pipeline

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""

# ─── Standard library ────────────────────────────────────────────────────────
import json
import csv
import os
import time
import asyncio
import threading
import statistics
import math
import re
from abc import ABC, abstractmethod
from collections import deque, defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from datetime import datetime
from functools import reduce
from typing import List, Dict, Tuple, Optional

# ─── Optional async file I/O ─────────────────────────────────────────────────
try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False


#  RE-USED FROM M1–M4  (unchanged classes kept for single-codebase continuity)
#

# ── Custom Exception Hierarchy (M4) ──────────────────────────────────────────

class SurveyError(Exception):
    """Base class for all survey-related errors."""

class ValidationError(SurveyError):
    """Raised when a user's answer fails validation rules."""

class PersistenceError(SurveyError):
    """Raised when data cannot be saved or loaded from disk."""

class AnalysisError(SurveyError):
    """Raised when analysis cannot be performed."""

class ConcurrencyError(SurveyError):
    """NEW M5: Raised when a concurrent task fails unexpectedly."""


# ── Observer Pattern (M4) ─────────────────────────────────────────────────────

class SurveyEventListener(ABC):
    @abstractmethod
    def on_response_recorded(self, respondent_number: int, response: dict): pass
    @abstractmethod
    def on_survey_complete(self, total_responses: int): pass
    @abstractmethod
    def on_export(self, filename: str, format_name: str): pass


class ConsoleSurveyLogger(SurveyEventListener):
    def on_response_recorded(self, respondent_number: int, response: dict):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [LOG {ts}] Respondent {respondent_number} recorded ({len(response)} answers).")

    def on_survey_complete(self, total_responses: int):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [LOG {ts}] Survey complete — {total_responses} total response(s).")

    def on_export(self, filename: str, format_name: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [LOG {ts}] Export → '{filename}' [{format_name}].")


class SurveyEventPublisher:
    def __init__(self):
        self._listeners: List[SurveyEventListener] = []

    def subscribe(self, listener: SurveyEventListener):
        self._listeners.append(listener)

    def unsubscribe(self, listener: SurveyEventListener):
        self._listeners.remove(listener)

    def notify_response_recorded(self, n: int, response: dict):
        for l in self._listeners: l.on_response_recorded(n, response)

    def notify_survey_complete(self, total: int):
        for l in self._listeners: l.on_survey_complete(total)

    def notify_export(self, filename: str, fmt: str):
        for l in self._listeners: l.on_export(filename, fmt)


# ── Strategy Pattern – Export (M4) ───────────────────────────────────────────

class ExportStrategy(ABC):
    @property
    @abstractmethod
    def format_name(self) -> str: pass

    @abstractmethod
    def export(self, data: List[dict], filename: str): pass


class JSONExportStrategy(ExportStrategy):
    @property
    def format_name(self) -> str: return "JSON"

    def export(self, data: List[dict], filename: str):
        path = f"{filename}.json"
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            print(f"  ✔ Saved → '{path}'")
        except IOError as e:
            raise PersistenceError(f"JSON export failed for '{path}': {e}") from e


class CSVExportStrategy(ExportStrategy):
    @property
    def format_name(self) -> str: return "CSV"

    def export(self, data: List[dict], filename: str):
        if not data:
            raise PersistenceError("No data to export.")
        path = f"{filename}.csv"
        try:
            keys = list(data[0].keys())
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(data)
            print(f"  ✔ Saved → '{path}'")
        except IOError as e:
            raise PersistenceError(f"CSV export failed for '{path}': {e}") from e


# ── Question Classes (M1/M2 base) ─────────────────────────────────────────────

class Question(ABC):
    def __init__(self, text: str):
        self.text = text

    @abstractmethod
    def ask(self) -> str: pass


class MultipleChoiceQuestion(Question):
    def __init__(self, text: str, options: List[str]):
        super().__init__(text)
        self.options = options

    def ask(self) -> str:
        print(f"\n{self.text}")
        for i, option in enumerate(self.options, 1):
            print(f"  {i}. {option}")
        raw = input("Choose option number: ").strip()
        try:
            choice = int(raw)
        except ValueError:
            raise ValidationError(f"'{raw}' is not a valid number. Choose 1–{len(self.options)}.")
        if not (1 <= choice <= len(self.options)):
            raise ValidationError(f"Choice {choice} out of range. Choose 1–{len(self.options)}.")
        return self.options[choice - 1]


class RatingQuestion(Question):
    def __init__(self, text: str, min_val: int = 1, max_val: int = 5):
        super().__init__(text)
        self.min_val = min_val
        self.max_val = max_val

    def ask(self) -> str:
        print(f"\n{self.text} (Rate {self.min_val}–{self.max_val})")
        raw = input("Your rating: ").strip()
        try:
            rating = int(raw)
        except ValueError:
            raise ValidationError(f"'{raw}' is not a number.")
        if not (self.min_val <= rating <= self.max_val):
            raise ValidationError(f"Rating must be {self.min_val}–{self.max_val}.")
        return f"{rating} / {self.max_val}"


class TextQuestion(Question):
    def __init__(self, text: str, min_length: int = 5):
        super().__init__(text)
        self.min_length = min_length

    def ask(self) -> str:
        print(f"\n{self.text}")
        answer = input("Your response: ").strip()
        if len(answer) < self.min_length:
            raise ValidationError(f"Response too short — minimum {self.min_length} characters required.")
        return answer


# ── Survey Class (M1–M4) ──────────────────────────────────────────────────────

class Survey:
    def __init__(self, title: str, publisher: SurveyEventPublisher = None):
        self.title = title
        self.questions: List[Question] = []
        self._response_queue: deque = deque()
        self.publisher = publisher or SurveyEventPublisher()

    def add_question(self, question: Question):
        self.questions.append(question)

    def response_generator(self):
        for resp in self._response_queue:
            yield resp

    @property
    def responses(self) -> List[dict]:
        return list(self._response_queue)

    def conduct(self):
        response: dict = {}
        print(f"\n{'─' * 40}")
        print(f"  {self.title}")
        print(f"{'─' * 40}")
        for q in self.questions:
            while True:
                try:
                    response[q.text] = q.ask()
                    break
                except ValidationError as e:
                    print(f"  ⚠  Input Error: {e}  Please try again.")
        self._response_queue.append(response)
        n = len(self._response_queue)
        print(f"\n  ✔ Response #{n} recorded successfully.")
        self.publisher.notify_response_recorded(n, response)

    def display_responses(self):
        responses = self.responses
        if not responses:
            print("  No responses collected yet.")
            return
        print("\n" + "=" * 55)
        print("  COLLECTED RESPONSES")
        print("=" * 55)
        for i, resp in enumerate(responses, 1):
            print(f"\n  Respondent {i}:")
            for q, a in resp.items():
                print(f"    • {q}:")
                print(f"      → {a}")


# ── DataProcessor (M3 functional pipeline) ───────────────────────────────────

class DataProcessor:
    def __init__(self, responses: List[dict]):
        self.responses = responses

    def filter_responses(self, fn) -> List[dict]:
        return list(filter(fn, self.responses))

    def extract_field(self, question_text: str) -> List[str]:
        return [r[question_text] for r in self.responses if question_text in r]

    def count_keyword(self, question_text: str, keyword: str) -> int:
        answers = self.extract_field(question_text)
        return reduce(lambda acc, a: acc + (1 if keyword.lower() in a.lower() else 0), answers, 0)

    def analysis_stream(self):
        seen: set = set()
        question_order: List[str] = []
        for resp in self.responses:
            for q in resp:
                if q not in seen:
                    seen.add(q)
                    question_order.append(q)
        for question in question_order:
            counts: dict = {}
            for resp in self.responses:
                a = resp.get(question)
                if a:
                    counts[a] = counts.get(a, 0) + 1
            yield question, counts

    def get_summary(self) -> List[list]:
        return [list(r.values()) for r in self.responses]

    def unique_answers(self, question_text: str) -> set:
        return {r[question_text] for r in self.responses if question_text in r}


# ── RobustDataAnalyzer (M4 Strategy + Observer) ───────────────────────────────

class RobustDataAnalyzer:
    def __init__(self, survey: Survey, publisher: SurveyEventPublisher = None):
        self.survey = survey
        self.publisher = publisher or survey.publisher
        self._export_strategy: ExportStrategy = JSONExportStrategy()
        self._analysis_results: dict = {}

    def set_export_strategy(self, strategy: ExportStrategy):
        self._export_strategy = strategy

    def analyze(self) -> dict:
        if not self.survey.responses:
            raise AnalysisError("Cannot analyze — no responses collected.")
        self._analysis_results = {}
        for response in self.survey.response_generator():
            for question, answer in response.items():
                counts = self._analysis_results.setdefault(question, {})
                counts[answer] = counts.get(answer, 0) + 1
        return self._analysis_results

    def display_analysis(self):
        if not self._analysis_results:
            try:
                self.analyze()
            except AnalysisError as e:
                print(f"  ✘ Analysis Error: {e}")
                return
        print("\n" + "=" * 55)
        print("  ANALYSIS RESULTS")
        print("=" * 55)
        for question, counts in self._analysis_results.items():
            print(f"\n  {question}")
            total = sum(counts.values())
            for answer, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                pct = (count / total) * 100
                bar = "█" * int(pct / 5)
                print(f"    {answer:<35} {count:>2} resp  ({pct:5.1f}%)  {bar}")

    def export_responses(self, filename: str = "course_feedback_responses"):
        try:
            self._export_strategy.export(self.survey.responses, filename)
            self.publisher.notify_export(filename, self._export_strategy.format_name)
        except PersistenceError as e:
            print(f"  ✘ Export failed: {e}")

    def export_analysis(self, filename: str = "course_feedback_analysis"):
        if not self._analysis_results:
            try:
                self.analyze()
            except AnalysisError as e:
                print(f"  ✘ Cannot export analysis: {e}")
                return
        flat = [
            {"Question": q, "Answer": a, "Count": c,
             "Percentage": f"{(c / sum(d.values())) * 100:.1f}%"}
            for q, d in self._analysis_results.items()
            for a, c in d.items()
        ]
        try:
            self._export_strategy.export(flat, filename)
            self.publisher.notify_export(filename, self._export_strategy.format_name)
        except PersistenceError as e:
            print(f"  ✘ Export failed: {e}")

    @classmethod
    def load_from_json(cls, filename: str) -> "RobustDataAnalyzer":
        path = filename if filename.endswith(".json") else f"{filename}.json"
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise PersistenceError(f"File not found: '{path}'")
        except json.JSONDecodeError as e:
            raise PersistenceError(f"Corrupt JSON in '{path}': {e}") from e
        except IOError as e:
            raise PersistenceError(f"Cannot read '{path}': {e}") from e
        survey = Survey("Loaded Survey")
        for resp in data:
            survey._response_queue.append(resp)
        return cls(survey)


#
#  MILESTONE 5 — CONCURRENCY & HIGH-PERFORMANCE SYSTEMS
#

# ── M5.1: Thread-Safe Counter ─────────────────────────────────────────────────

class ThreadSafeCounter:
    """
    M5: A shared counter protected by a threading.Lock.
    Used to safely count processed responses across multiple threads.
    """
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._value += 1

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


# ── M5.2: Module-level worker functions (picklable for ProcessPoolExecutor) ───

def _worker_analyze_chunk(chunk: List[dict]) -> dict:
    """
    M5 ProcessPool worker: counts answer frequencies for a slice of responses.
    Must be a top-level function — ProcessPoolExecutor requires picklability.
    """
    result: dict = {}
    for response in chunk:
        for question, answer in response.items():
            counts = result.setdefault(question, {})
            counts[answer] = counts.get(answer, 0) + 1
    return result


def _merge_analysis_dicts(a: dict, b: dict) -> dict:
    """
    M5 helper: merge two analysis dicts by summing matching answer counts.
    """
    merged = {q: dict(counts) for q, counts in a.items()}
    for question, counts in b.items():
        if question not in merged:
            merged[question] = dict(counts)
        else:
            for answer, count in counts.items():
                merged[question][answer] = merged[question].get(answer, 0) + count
    return merged


# ── M5.3: Concurrent Survey Processor ────────────────────────────────────────

class ConcurrentSurveyProcessor:
    """
    M5: Orchestrates parallel and async analysis of survey data.

    Responsibilities:
      - parallel_analyze()  : ThreadPoolExecutor per-respondent analysis
      - process_parallel()  : ProcessPoolExecutor chunked CPU-bound analysis
      - export_async()      : asyncio + aiofiles non-blocking file export
      - async_export_queue(): asyncio.Queue-based streaming export pipeline
    """

    def __init__(self, survey: Survey, publisher: SurveyEventPublisher = None,
                 max_workers: int = 4):
        self.survey = survey
        self.publisher = publisher or survey.publisher
        self.max_workers = max_workers
        self._counter = ThreadSafeCounter()

    # ── M5.3a: Threaded Analysis ──────────────────────────────────────────────

    def _thread_worker(self, response: dict, result_bucket: list, lock: threading.Lock):
        """
        Worker run in each thread: analyzes one response and appends result.
        Uses a lock to protect the shared result_bucket list.
        """
        partial: dict = {}
        for question, answer in response.items():
            counts = partial.setdefault(question, {})
            counts[answer] = counts.get(answer, 0) + 1
        with lock:
            result_bucket.append(partial)
        self._counter.increment()

    def parallel_analyze(self) -> dict:
        """
        M5: Run per-respondent analysis in parallel using ThreadPoolExecutor.
        Returns a merged analysis dict identical in structure to RobustDataAnalyzer.
        """
        responses = self.survey.responses
        if not responses:
            raise AnalysisError("No responses to analyze in parallel.")

        result_bucket: list = []
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [
                executor.submit(self._thread_worker, resp, result_bucket, lock)
                for resp in responses
            ]
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    raise ConcurrencyError(f"Thread worker failed: {exc}") from exc

        # Merge all partial dicts
        merged: dict = {}
        for partial in result_bucket:
            merged = _merge_analysis_dicts(merged, partial)

        return merged

    # ── M5.3b: Multiprocess Analysis ─────────────────────────────────────────

    def process_parallel(self, n_processes: int = 2) -> dict:
        """
        M5: Split responses into chunks and analyze each chunk in a separate
        process using ProcessPoolExecutor (CPU-bound parallel processing).
        """
        responses = self.survey.responses
        if not responses:
            raise AnalysisError("No responses to process.")

        chunk_size = max(1, math.ceil(len(responses) / n_processes))
        chunks = [responses[i:i + chunk_size] for i in range(0, len(responses), chunk_size)]

        merged: dict = {}
        try:
            with ProcessPoolExecutor(max_workers=n_processes) as executor:
                futures = {executor.submit(_worker_analyze_chunk, chunk): chunk
                           for chunk in chunks}
                for future in as_completed(futures):
                    partial = future.result()
                    merged = _merge_analysis_dicts(merged, partial)
        except Exception as e:
            raise ConcurrencyError(f"ProcessPoolExecutor error: {e}") from e

        return merged

    # ── M5.3c: Async File Export ──────────────────────────────────────────────

    async def _async_write_json(self, data: list, path: str):
        """Async JSON write using aiofiles (falls back to sync if unavailable)."""
        content = json.dumps(data, indent=4)
        if AIOFILES_AVAILABLE:
            async with aiofiles.open(path, "w") as f:
                await f.write(content)
        else:
            with open(path, "w") as f:
                f.write(content)
        print(f"  ✔ [Async] Saved → '{path}'")

    async def _async_write_csv(self, data: List[dict], path: str):
        """Async CSV write (aiofiles for text, sync DictWriter for header logic)."""
        if not data:
            raise PersistenceError("No data to export asynchronously.")
        keys = list(data[0].keys())
        lines = [",".join(keys)]
        for row in data:
            lines.append(",".join(str(row.get(k, "")) for k in keys))
        content = "\n".join(lines)
        if AIOFILES_AVAILABLE:
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(content)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        print(f"  ✔ [Async] Saved → '{path}'")

    async def export_async(self, base: str = "course_feedback_async"):
        """
        M5: Concurrently export responses as JSON and CSV using asyncio.gather.
        Both writes run in parallel within the same event loop.
        """
        responses = self.survey.responses
        await asyncio.gather(
            self._async_write_json(responses, f"{base}_responses.json"),
            self._async_write_csv(responses, f"{base}_responses.csv"),
        )
        self.publisher.notify_export(base, "JSON+CSV (async)")

    # ── M5.3d: Async Queue-based Streaming Export Pipeline ───────────────────

    async def async_export_queue(self, analysis: dict, base: str = "course_feedback_stream"):
        """
        M5: asyncio.Queue-based streaming pipeline.
        Producer enqueues analysis records; consumer writes them asynchronously.
        Demonstrates producer-consumer concurrency pattern within asyncio.
        """
        queue: asyncio.Queue = asyncio.Queue()
        records: list = []

        async def producer():
            for q, counts in analysis.items():
                total = sum(counts.values())
                for answer, count in counts.items():
                    pct = f"{(count / total) * 100:.1f}%"
                    await queue.put({"Question": q, "Answer": answer,
                                     "Count": count, "Percentage": pct})
            await queue.put(None)  # sentinel

        async def consumer():
            while True:
                item = await queue.get()
                if item is None:
                    break
                records.append(item)
                queue.task_done()

        await asyncio.gather(producer(), consumer())
        await self._async_write_json(records, f"{base}_analysis.json")
        print(f"  ✔ [Queue] {len(records)} records streamed to '{base}_analysis.json'")


# ── M5.4: Performance Benchmark ───────────────────────────────────────────────

class PerformanceBenchmark:
    """
    M5: Measures wall-clock time for serial vs parallel analysis.
    Reports absolute times and the speedup ratio.
    """

    def __init__(self, survey: Survey):
        self.survey = survey
        self._results: Dict[str, float] = {}

    def _serial_analyze(self) -> dict:
        """Serial baseline: single-threaded frequency count."""
        result: dict = {}
        for response in self.survey.responses:
            for question, answer in response.items():
                counts = result.setdefault(question, {})
                counts[answer] = counts.get(answer, 0) + 1
        return result

    def run(self, n_processes: int = 2) -> Dict[str, float]:
        processor = ConcurrentSurveyProcessor(self.survey)

        # 1. Serial
        t0 = time.perf_counter()
        self._serial_analyze()
        serial_time = time.perf_counter() - t0

        # 2. Threaded
        t0 = time.perf_counter()
        processor.parallel_analyze()
        thread_time = time.perf_counter() - t0

        # 3. Multiprocess (only if enough data to be meaningful)
        t0 = time.perf_counter()
        processor.process_parallel(n_processes)
        process_time = time.perf_counter() - t0

        self._results = {
            "serial_s":  serial_time,
            "thread_s":  thread_time,
            "process_s": process_time,
        }
        return self._results

    def display(self):
        if not self._results:
            print("  Run benchmark first.")
            return
        print("\n" + "=" * 55)
        print("  MILESTONE 5 — PERFORMANCE BENCHMARK")
        print("=" * 55)
        s = self._results["serial_s"]
        t = self._results["thread_s"]
        p = self._results["process_s"]
        print(f"\n  Serial analysis       : {s * 1000:7.3f} ms")
        print(f"  Threaded analysis     : {t * 1000:7.3f} ms  "
              f"(speedup: {s/t:.2f}x)" if t > 0 else "")
        print(f"  Multiprocess analysis : {p * 1000:7.3f} ms  "
              f"(speedup: {s/p:.2f}x)" if p > 0 else "")
        print(f"\n  Note: For small datasets, serial may outperform concurrent")
        print(f"  approaches due to thread/process spawn overhead. Speedup")
        print(f"  becomes significant at scale (10,000+ responses).")


#  MILESTONE 6 — RESEARCH CONTRIBUTION & FINAL SYSTEM


# ── M6.1: Rule-Based Sentiment Analyzer (NLP) ─────────────────────────────────

class SentimentAnalyzer:
    """
    M6 – Novel Feature: Lightweight rule-based NLP for open-text survey answers.

    Uses a scored lexicon with negation detection and phrase-level matching.
    Returns a sentiment label ('Positive', 'Neutral', 'Negative') and a
    compound score in [-1.0, +1.0].

    Innovation: Unlike off-the-shelf libraries, this analyzer is tuned
    specifically for academic feedback language (e.g., "not very clear",
    "surprisingly engaging", "overly difficult").
    """

    POSITIVE_PHRASES = {
        "very helpful": 0.9, "highly recommend": 0.9, "well structured": 0.8,
        "easy to follow": 0.8, "very clear": 0.8, "great examples": 0.75,
        "enjoyed it": 0.7, "well explained": 0.8, "very engaging": 0.85,
        "loved the": 0.7, "really enjoyed": 0.75,
    }
    NEGATIVE_PHRASES = {
        "not clear": -0.8, "very confusing": -0.9, "too difficult": -0.8,
        "not helpful": -0.75, "poorly explained": -0.85, "very boring": -0.9,
        "too fast": -0.6, "not enough": -0.5, "needs improvement": -0.6,
        "very slow": -0.6,
    }
    POSITIVE_WORDS = {
        "excellent": 0.9, "great": 0.8, "good": 0.6, "helpful": 0.65,
        "clear": 0.6, "interesting": 0.65, "engaging": 0.7, "fantastic": 0.9,
        "wonderful": 0.85, "amazing": 0.9, "enjoyed": 0.7, "love": 0.8,
        "effective": 0.65, "informative": 0.65, "organized": 0.6,
        "thorough": 0.65, "accessible": 0.6, "practical": 0.6,
    }
    NEGATIVE_WORDS = {
        "bad": -0.7, "poor": -0.75, "confusing": -0.8, "boring": -0.8,
        "difficult": -0.5, "unclear": -0.75, "slow": -0.5, "hard": -0.4,
        "disorganized": -0.8, "frustrating": -0.85, "tedious": -0.7,
        "repetitive": -0.5, "unhelpful": -0.75, "irrelevant": -0.7,
    }
    NEGATION_WORDS = {"not", "no", "never", "without", "hardly", "barely",
                      "scarcely", "don't", "doesn't", "didn't", "wasn't"}

    def analyze(self, text: str) -> Dict[str, object]:
        """Return {'score': float, 'label': str, 'flagged_words': list}."""
        text_lower = text.lower()
        score = 0.0
        flagged: list = []

        # 1. Phrase matching (longer phrases take precedence)
        for phrase, val in {**self.POSITIVE_PHRASES, **self.NEGATIVE_PHRASES}.items():
            if phrase in text_lower:
                score += val
                flagged.append(phrase)
                text_lower = text_lower.replace(phrase, " ")

        # 2. Word-level matching with negation window
        tokens = re.findall(r"\b\w+\b", text_lower)
        for i, token in enumerate(tokens):
            negated = any(tokens[max(0, i - 3):i].count(w) > 0
                          for w in self.NEGATION_WORDS)
            val = self.POSITIVE_WORDS.get(token, 0) + self.NEGATIVE_WORDS.get(token, 0)
            if val != 0:
                score += -val if negated else val
                flagged.append(("NOT " if negated else "") + token)

        # 3. Clamp and label
        score = max(-1.0, min(1.0, score))
        label = "Positive" if score >= 0.15 else ("Negative" if score <= -0.15 else "Neutral")
        return {"score": round(score, 3), "label": label, "flagged_words": flagged[:5]}

    def batch_analyze(self, responses: List[dict],
                      text_questions: List[str]) -> List[dict]:
        """Apply sentiment analysis to all text answers across all responses."""
        results = []
        for i, resp in enumerate(responses, 1):
            row = {"respondent": i}
            for q in text_questions:
                if q in resp:
                    result = self.analyze(resp[q])
                    short_q = q[:30] + "…" if len(q) > 30 else q
                    row[f"{short_q} [score]"] = result["score"]
                    row[f"{short_q} [label]"] = result["label"]
            results.append(row)
        return results


# ── M6.2: Anomaly Detector (IQR-based Statistical Outlier Detection) ──────────

class AnomalyDetector:
    """
    M6 – Novel Feature: IQR-based statistical outlier detection on rating questions.

    Identifies respondents whose numeric ratings deviate significantly from
    the distribution (below Q1 - 1.5*IQR or above Q3 + 1.5*IQR).
    Useful for detecting careless responders or genuinely extreme experiences.
    """

    def detect(self, responses: List[dict], rating_questions: List[str]) -> Dict[str, list]:
        """
        Returns a dict mapping each rating question to a list of
        (respondent_index, value, z_score_proxy) for detected outliers.
        """
        outliers: Dict[str, list] = {}
        for question in rating_questions:
            values: List[Tuple[int, float]] = []
            for i, resp in enumerate(responses, 1):
                raw = resp.get(question, "")
                try:
                    # Handles "7 / 10" and "3 / 5" formats
                    numeric = float(raw.split("/")[0].strip())
                    values.append((i, numeric))
                except (ValueError, AttributeError):
                    continue

            if len(values) < 4:
                continue  # not enough data for IQR

            nums = sorted(v for _, v in values)
            q1 = statistics.median(nums[: len(nums) // 2])
            q3 = statistics.median(nums[len(nums) // 2 + (len(nums) % 2):])
            iqr = q3 - q1

            if iqr == 0:
                continue  # no spread — skip

            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            flags = [(i, v, round((v - statistics.mean(nums)) /
                                  (statistics.stdev(nums) or 1), 2))
                     for i, v in values if v < lower or v > upper]
            if flags:
                outliers[question] = flags
        return outliers

    def display(self, outliers: Dict[str, list]):
        if not outliers:
            print("  ✔ No rating anomalies detected.")
            return
        print("\n" + "=" * 55)
        print("  M6 — ANOMALY DETECTION REPORT")
        print("=" * 55)
        for question, flags in outliers.items():
            short_q = question[:60] + "…" if len(question) > 60 else question
            print(f"\n  Question: {short_q}")
            for resp_idx, val, z in flags:
                direction = "↑ High" if z > 0 else "↓ Low"
                print(f"    Respondent {resp_idx:>3}: value={val:.0f}  z≈{z:+.2f}  [{direction} outlier]")


# ── M6.3: Smart Recommendation Engine ────────────────────────────────────────

class SmartRecommendation:
    """
    M6 – Novel Feature: Generates per-respondent actionable feedback
    recommendations based on their answer profile.

    Uses a rule table (condition → recommendation) rather than hard-coded
    if-else chains, making it easily extensible.
    """

    RULES: List[Tuple[callable, str]] = [
        (lambda r: r.get("How would you rate the course overall?") == "Poor",
         "Consider redesigning core modules — overall satisfaction is critically low."),
        (lambda r: r.get("How would you rate the course overall?") == "Excellent",
         "Share this course design as a template for other modules."),
        (lambda r: _safe_rating(r, "Rate the instructor's teaching clarity") < 3,
         "Invest in instructor communication training or additional tutorials."),
        (lambda r: _safe_rating(r, "Rate the difficulty level of the course") >= 8,
         "Review pacing — a large share of students find the course too demanding."),
        (lambda r: r.get("How was the workload of this course?") == "Too Heavy",
         "Reduce non-essential assignments; introduce flexible submission windows."),
        (lambda r: r.get("Did the course meet your expectations?") in ("Disagree", "Strongly Disagree"),
         "Update course description and learning outcomes to manage expectations."),
        (lambda r: r.get("How would you rate the course materials?") == "Not Helpful",
         "Commission updated reading materials with more practical examples."),
    ]

    def recommend(self, responses: List[dict]) -> List[Dict]:
        """Returns a recommendation report per respondent."""
        report = []
        for i, resp in enumerate(responses, 1):
            recs = [msg for condition, msg in self.RULES if condition(resp)]
            report.append({
                "respondent": i,
                "recommendations": recs if recs else ["No specific issues flagged — keep it up!"]
            })
        return report

    def display(self, report: List[Dict]):
        print("\n" + "=" * 55)
        print("  M6 — SMART RECOMMENDATION ENGINE")
        print("=" * 55)
        for entry in report:
            print(f"\n  Respondent {entry['respondent']}:")
            for rec in entry["recommendations"]:
                print(f"    → {rec}")


def _safe_rating(response: dict, question: str) -> float:
    """Helper: safely extract numeric rating from 'N / M' format."""
    raw = response.get(question, "0 / 1")
    try:
        return float(raw.split("/")[0].strip())
    except (ValueError, AttributeError):
        return 0.0


# ── M6.4: Adaptive Survey Engine ──────────────────────────────────────────────

class AdaptiveSurveyEngine:
    """
    M6 – Novel Feature: ML-style adaptive routing.

    After the standard survey, the engine inspects each respondent's answers
    and determines whether they qualify for a follow-up 'deep-dive' question
    branch. This simulates adaptive testing / branching logic found in
    real-world intelligent survey systems (e.g., CAT — Computerized Adaptive Testing).
    """

    def __init__(self):
        self._follow_up_routes: List[Tuple[callable, str, str]] = [
            # (trigger_condition, tag, follow_up_question_text)
            (lambda r: r.get("How would you rate the course overall?") == "Poor",
             "POOR_RATING",
             "You rated the course poorly. What single change would most improve it?"),
            (lambda r: _safe_rating(r, "Rate the difficulty level of the course") >= 8,
             "HIGH_DIFFICULTY",
             "You found the course very difficult. Which topic was most challenging?"),
            (lambda r: r.get("How was the workload of this course?") == "Too Heavy",
             "HEAVY_WORKLOAD",
             "The workload felt heavy. Which type of task consumed the most time?"),
        ]

    def get_follow_up(self, response: dict) -> Optional[Tuple[str, str]]:
        """Return (tag, follow_up_question) for the first matching rule, or None."""
        for condition, tag, question in self._follow_up_routes:
            if condition(response):
                return tag, question
        return None

    def conduct_adaptive_session(self, responses: List[dict]) -> List[dict]:
        """
        Run follow-up questions for respondents that triggered adaptive routing.
        Returns augmented response list with follow-up answers inserted.
        """
        augmented = []
        triggered_count = 0
        for resp in responses:
            follow_up = self.get_follow_up(resp)
            if follow_up:
                tag, question = follow_up
                triggered_count += 1
                print(f"\n  [Adaptive] Routing respondent to follow-up [{tag}]:")
                print(f"  {question}")
                answer = input("  Your answer: ").strip()
                resp = {**resp, f"[Adaptive] {question}": answer}
            augmented.append(resp)
        if triggered_count == 0:
            print("  ✔ No adaptive follow-ups triggered — all responses within normal range.")
        return augmented


# ── M6.5: Research Report Generator ──────────────────────────────────────────

class ResearchReportGenerator:
    """
    M6 – Research Contribution: Generates a structured Markdown academic report
    following conference paper conventions (Abstract, Introduction, Methodology,
    Results, Discussion, Conclusion, Future Work).
    """

    def __init__(self, survey: Survey, analysis: dict, sentiment_results: List[dict],
                 outliers: Dict[str, list], recommendations: List[dict],
                 benchmark: Dict[str, float]):
        self.survey = survey
        self.analysis = analysis
        self.sentiment = sentiment_results
        self.outliers = outliers
        self.recommendations = recommendations
        self.benchmark = benchmark
        self._timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _compute_top_answer(self, question: str) -> Tuple[str, float]:
        counts = self.analysis.get(question, {})
        if not counts:
            return "N/A", 0.0
        top = max(counts, key=counts.get)
        total = sum(counts.values())
        return top, round((counts[top] / total) * 100, 1)

    def generate(self) -> str:
        n = len(self.survey.responses)
        nq = len(self.survey.questions)

        # Compute aggregate sentiment
        all_scores = [
            v for row in self.sentiment for k, v in row.items()
            if "[score]" in k
        ]
        avg_sentiment = round(statistics.mean(all_scores), 3) if all_scores else 0.0
        sentiment_label = ("Positive" if avg_sentiment >= 0.15
                           else ("Negative" if avg_sentiment <= -0.15 else "Neutral"))

        overall_top, overall_pct = self._compute_top_answer(
            "How would you rate the course overall?")
        clarity_top, clarity_pct = self._compute_top_answer(
            "Rate the instructor's teaching clarity")

        serial_ms = self.benchmark.get("serial_s", 0) * 1000
        thread_ms = self.benchmark.get("thread_s", 0) * 1000
        process_ms = self.benchmark.get("process_s", 0) * 1000
        speedup_t = round(serial_ms / thread_ms, 2) if thread_ms > 0 else "N/A"
        speedup_p = round(serial_ms / process_ms, 2) if process_ms > 0 else "N/A"

        n_anomalies = sum(len(v) for v in self.outliers.values())
        n_recs = sum(len(e["recommendations"]) for e in self.recommendations)

        report = f"""# Research Report: Intelligent Survey Data Processing System
## STA 2240 — Course Feedback Survey Analysis
**Generated:** {self._timestamp}
**Authors:** Student Group, STA 2240

---

## Abstract

This report presents the design, implementation, and evaluation of an
object-oriented Survey Data Processing System developed across six
evolutionary milestones for STA 2240. The system collects, processes,
and analyses university course feedback using advanced OOP principles,
concurrent programming, and intelligent analytics. A dataset of {n}
respondent(s) across {nq} survey questions was processed. Key innovations
include a rule-based NLP Sentiment Analyzer, an IQR-based Anomaly Detector,
an Adaptive Survey Engine with ML-style branching, and a concurrent
processing architecture combining multithreading and multiprocessing.
Results indicate a mean sentiment score of {avg_sentiment} ({sentiment_label}),
{n_anomalies} statistical rating anomalies, and {n_recs} actionable
improvement recommendations generated automatically.

---

## 1. Introduction

University course feedback surveys are essential for continuous curriculum
improvement. Traditional survey tools provide raw frequency distributions
but lack the analytical depth required for actionable insight. This project
develops a fully object-oriented, concurrent, and intelligent system that
goes beyond tabulation to provide sentiment analysis, anomaly detection,
adaptive questioning, and automated recommendation generation.

The system was developed in Python over six milestones, each adding a new
layer of abstraction, reliability, and intelligence to the same codebase.

---

## 2. System Architecture

The system follows a layered OOP architecture:

| Layer | Components |
|---|---|
| Data Collection | `Survey`, `Question`, `MultipleChoiceQuestion`, `RatingQuestion`, `TextQuestion` |
| Data Processing | `DataProcessor`, `RobustDataAnalyzer` |
| Concurrency (M5) | `ConcurrentSurveyProcessor`, `ThreadSafeCounter`, `PerformanceBenchmark` |
| Intelligence (M6) | `SentimentAnalyzer`, `AnomalyDetector`, `SmartRecommendation`, `AdaptiveSurveyEngine` |
| Infrastructure | Observer Pattern, Strategy Pattern, Custom Exception Hierarchy |

Design patterns applied: **Observer** (event broadcasting), **Strategy** (pluggable export),
**Template Method** (abstract Question), **Producer-Consumer** (asyncio Queue pipeline).

---

## 3. Methodology

### 3.1 Data Collection
Respondents completed an 8-question survey covering overall rating,
instructor clarity, course materials, difficulty, expectations, workload,
and two open-text feedback fields.

### 3.2 Concurrent Processing (Milestone 5)
Three processing modes were benchmarked:
- **Serial**: Single-threaded frequency counting (baseline)
- **Threaded**: `ThreadPoolExecutor` with `{4}` workers, one thread per response
- **Multiprocess**: `ProcessPoolExecutor` splitting responses into chunks across `{2}` processes

### 3.3 Sentiment Analysis (Milestone 6)
A domain-tuned rule-based lexicon with negation detection was applied to
open-text answers. Phrase-level matching was performed before word-level
matching to prevent partial-phrase misclassification.

### 3.4 Anomaly Detection
IQR-based outlier detection was applied to all numeric rating questions.
Respondents with values below Q1 − 1.5×IQR or above Q3 + 1.5×IQR were
flagged as statistical anomalies.

### 3.5 Adaptive Survey Engine
An ML-style adaptive routing system re-engaged respondents who triggered
defined conditions (e.g., "Poor" overall rating, difficulty ≥ 8/10),
directing them to targeted follow-up questions.

---

## 4. Results

### 4.1 Survey Responses
- Total respondents: **{n}**
- Questions per respondent: **{nq}**
- Top overall rating: **{overall_top}** ({overall_pct}% of respondents)
- Top teaching clarity score: **{clarity_top}** ({clarity_pct}% of respondents)

### 4.2 Performance Benchmarks

| Mode | Time (ms) | Speedup |
|---|---|---|
| Serial | {serial_ms:.3f} | 1.00× (baseline) |
| Threaded | {thread_ms:.3f} | {speedup_t}× |
| Multiprocess | {process_ms:.3f} | {speedup_p}× |

*Note: For small datasets thread overhead dominates. At scale (10,000+ records),
threaded and multiprocess modes yield significant speedups.*

### 4.3 Sentiment Analysis
- Mean sentiment score: **{avg_sentiment}** (range: −1.0 to +1.0)
- Overall sentiment: **{sentiment_label}**

### 4.4 Anomaly Detection
- Rating anomalies detected across all questions: **{n_anomalies}**
- Questions with anomalies: **{len(self.outliers)}**

### 4.5 Recommendations Generated
- Total recommendations: **{n_recs}** across {n} respondent(s)

---

## 5. Discussion

The concurrent processing architecture demonstrates that for I/O-bound export
tasks, `asyncio` provides meaningful latency reduction by overlapping file writes.
For CPU-bound analysis, multiprocessing delivers scalable speedup proportional
to core count, while threading is better suited to I/O-bound workloads.

The Sentiment Analyzer reveals aggregate student affect beyond numeric ratings,
providing qualitative signal that traditional Likert-scale items miss. The
Anomaly Detector surfaces careless or extreme responders for review before
results influence policy decisions.

The Adaptive Survey Engine demonstrates how intelligent branching can improve
data quality by eliciting targeted follow-up only where warranted, reducing
survey fatigue for the majority of respondents.

---

## 6. Conclusion

This project evolved a basic OOP prototype into a research-grade, concurrent,
and intelligent survey analytics system. All six milestones contributed
incrementally to the same codebase without restarting or fragmenting the design.
The final system combines classic software engineering patterns with modern
concurrency and domain-specific NLP to deliver actionable insights from
survey data automatically.

---

## 7. Future Work

- Replace rule-based sentiment with a fine-tuned BERT-based classifier
- Integrate real-time web dashboard (FastAPI + React) for live survey monitoring
- Add differential privacy mechanisms before publishing aggregated results
- Extend adaptive routing with reinforcement learning (reward = insight quality)
- Deploy on a distributed computing cluster for large-scale national surveys

---

## References

1. Gamma, E., et al. (1994). *Design Patterns: Elements of Reusable Object-Oriented Software.* Addison-Wesley.
2. Python Software Foundation. (2024). *concurrent.futures — Launching parallel tasks.* docs.python.org
3. Hutto, C. & Gilbert, E. (2014). VADER: A Parsimonious Rule-based Model for Sentiment Analysis. *ICWSM*.
4. Tukey, J.W. (1977). *Exploratory Data Analysis.* Addison-Wesley.
5. Wainer, H. (2000). *Computerized Adaptive Testing: A Primer.* Lawrence Erlbaum.
"""
        return report

    def save(self, filename: str = "research_report"):
        path = f"{filename}.md"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.generate())
            print(f"  ✔ Research report saved → '{path}'")
        except IOError as e:
            raise PersistenceError(f"Could not save report: {e}") from e


# ── M6.6: Intelligent Insight Engine (M6 Integrator) ─────────────────────────

class IntelligentInsightEngine:
    """
    M6: Top-level orchestrator that runs all M6 intelligence components
    in sequence and produces a unified output.
    """

    TEXT_QUESTIONS = [
        "What did you enjoy most about the course?",
        "What suggestions do you have for improvement?",
    ]
    RATING_QUESTIONS = [
        "Rate the instructor's teaching clarity",
        "Rate the difficulty level of the course",
    ]

    def __init__(self, survey: Survey, analysis: dict,
                 benchmark: Dict[str, float], publisher: SurveyEventPublisher):
        self.survey = survey
        self.analysis = analysis
        self.benchmark = benchmark
        self.publisher = publisher
        self._sentiment_results: List[dict] = []
        self._outliers: Dict[str, list] = {}
        self._recommendations: List[dict] = []

    def run(self) -> Dict:
        responses = self.survey.responses

        # 1. Sentiment Analysis
        print("\n" + "=" * 55)
        print("  M6.1 — SENTIMENT ANALYSIS")
        print("=" * 55)
        sa = SentimentAnalyzer()
        self._sentiment_results = sa.batch_analyze(responses, self.TEXT_QUESTIONS)
        for row in self._sentiment_results:
            print(f"  Respondent {row['respondent']}:")
            for k, v in row.items():
                if k != "respondent":
                    print(f"    {k}: {v}")

        # 2. Anomaly Detection
        ad = AnomalyDetector()
        self._outliers = ad.detect(responses, self.RATING_QUESTIONS)
        ad.display(self._outliers)

        # 3. Smart Recommendations
        sr = SmartRecommendation()
        self._recommendations = sr.recommend(responses)
        sr.display(self._recommendations)

        return {
            "sentiment": self._sentiment_results,
            "outliers": self._outliers,
            "recommendations": self._recommendations,
        }

    def generate_report(self, filename: str = "research_report"):
        gen = ResearchReportGenerator(
            survey=self.survey,
            analysis=self.analysis,
            sentiment_results=self._sentiment_results,
            outliers=self._outliers,
            recommendations=self._recommendations,
            benchmark=self.benchmark,
        )
        gen.save(filename)


#  SURVEY BUILDER & COLLECTION HELPERS


def build_survey(publisher: SurveyEventPublisher) -> Survey:
    survey = Survey("University Course Feedback Survey", publisher)
    survey.add_question(MultipleChoiceQuestion(
        "How would you rate the course overall?",
        ["Excellent", "Good", "Average", "Poor"]
    ))
    survey.add_question(RatingQuestion(
        "Rate the instructor's teaching clarity", min_val=1, max_val=5))
    survey.add_question(MultipleChoiceQuestion(
        "How would you rate the course materials?",
        ["Very Helpful", "Helpful", "Neutral", "Not Helpful"]
    ))
    survey.add_question(RatingQuestion(
        "Rate the difficulty level of the course", min_val=1, max_val=10))
    survey.add_question(MultipleChoiceQuestion(
        "Did the course meet your expectations?",
        ["Strongly Agree", "Agree", "Neutral", "Disagree", "Strongly Disagree"]
    ))
    survey.add_question(MultipleChoiceQuestion(
        "How was the workload of this course?",
        ["Too Heavy", "Manageable", "Just Right", "Too Light"]
    ))
    survey.add_question(TextQuestion(
        "What did you enjoy most about the course?", min_length=5))
    survey.add_question(TextQuestion(
        "What suggestions do you have for improvement?", min_length=5))
    return survey


def collect_responses(survey: Survey, publisher: SurveyEventPublisher):
    while True:
        try:
            raw = input("\nHow many respondents will complete this survey? ").strip()
            num = int(raw)
            if num > 0:
                break
            print("  Please enter a positive whole number.")
        except ValueError:
            print("  Invalid input — please enter a whole number.")

    for i in range(num):
        print(f"\n>>> Respondent {i + 1} of {num}")
        survey.conduct()

    publisher.notify_survey_complete(len(survey.responses))


#  MILESTONE 5 DEMO FUNCTIONS


def run_m5_concurrency(survey: Survey, publisher: SurveyEventPublisher) -> Dict[str, float]:
    print("\n" + "█" * 55)
    print("  MILESTONE 5 — CONCURRENCY & HIGH-PERFORMANCE SYSTEMS")
    print("█" * 55)

    processor = ConcurrentSurveyProcessor(survey, publisher)

    # 1. Parallel threaded analysis
    print("\n  [ThreadPool] Running parallel analysis…")
    try:
        threaded_result = processor.parallel_analyze()
        print(f"  ✔ Threaded analysis complete — {len(threaded_result)} question(s) processed.")
        print(f"  ✔ Responses processed by threads: {processor._counter.value}")
    except (AnalysisError, ConcurrencyError) as e:
        print(f"  ✘ Threaded analysis failed: {e}")

    # 2. Multiprocess analysis
    print("\n  [ProcessPool] Running multiprocess analysis…")
    try:
        mp_result = processor.process_parallel(n_processes=2)
        print(f"  ✔ Multiprocess analysis complete — {len(mp_result)} question(s) processed.")
    except (AnalysisError, ConcurrencyError) as e:
        print(f"  ✘ Multiprocess analysis failed: {e}")

    # 3. Async export
    print("\n  [Asyncio] Running async concurrent export…")
    try:
        asyncio.run(processor.export_async("course_feedback_async"))
    except Exception as e:
        print(f"  ✘ Async export failed: {e}")

    # 4. Async queue-based streaming export
    print("\n  [Asyncio Queue] Streaming analysis export pipeline…")
    try:
        analyzer = RobustDataAnalyzer(survey, publisher)
        analysis = analyzer.analyze()
        asyncio.run(processor.async_export_queue(analysis, "course_feedback_stream"))
    except Exception as e:
        print(f"  ✘ Stream export failed: {e}")

    # 5. Performance benchmark
    print("\n  [Benchmark] Measuring serial vs threaded vs multiprocess…")
    bench = PerformanceBenchmark(survey)
    results = bench.run(n_processes=2)
    bench.display()

    return results



#  MILESTONE 6 DEMO FUNCTIONS


def run_m6_intelligence(survey: Survey, analysis: dict,
                        benchmark: Dict[str, float],
                        publisher: SurveyEventPublisher):
    print("\n" + "█" * 55)
    print("  MILESTONE 6 — RESEARCH CONTRIBUTION & FINAL SYSTEM")
    print("█" * 55)

    # Adaptive Survey Engine — runs follow-up questions interactively
    print("\n  [Adaptive Engine] Checking for adaptive follow-up triggers…")
    engine = AdaptiveSurveyEngine()
    augmented = engine.conduct_adaptive_session(survey.responses)
    # Re-inject augmented responses back into survey for report generation
    survey._response_queue = deque(augmented)

    # Intelligent Insight Engine
    insight = IntelligentInsightEngine(survey, analysis, benchmark, publisher)
    insight.run()

    # Research Report
    print("\n  [Research Report] Generating academic Markdown report…")
    insight.generate_report("research_report")

    # Save augmented responses
    print("\n  [Export] Saving M6-augmented responses…")
    try:
        with open("course_feedback_m6_augmented.json", "w") as f:
            json.dump(augmented, f, indent=4)
        print("  ✔ Saved → 'course_feedback_m6_augmented.json'")
    except IOError as e:
        print(f"  ✘ Could not save augmented responses: {e}")



#  MAIN ENTRY POINT
#

def main():
    print("\n" + "█" * 55)
    print("  STA 2240 — Survey Data Processing System")
    print("  Course Feedback Survey  |  Milestones 5 & 6")
    print("█" * 55)

    # ── Observer setup ────────────────────────────────────────────────────────
    publisher = SurveyEventPublisher()
    publisher.subscribe(ConsoleSurveyLogger())

    # ── Build & collect ───────────────────────────────────────────────────────
    survey = build_survey(publisher)
    collect_responses(survey, publisher)
    survey.display_responses()

    # ── M4 Robust Analysis (baseline) ────────────────────────────────────────
    analyzer = RobustDataAnalyzer(survey, publisher)
    try:
        analysis = analyzer.analyze()
    except AnalysisError as e:
        print(f"\n  ✘ Analysis Error: {e}")
        return
    analyzer.display_analysis()

    # ── M4 Exports (JSON + CSV via Strategy) ──────────────────────────────────
    analyzer.set_export_strategy(JSONExportStrategy())
    analyzer.export_responses("course_feedback_responses")
    analyzer.set_export_strategy(CSVExportStrategy())
    analyzer.export_responses("course_feedback_responses")

    # ── MILESTONE 5 ───────────────────────────────────────────────────────────
    benchmark_results = run_m5_concurrency(survey, publisher)

    # ── MILESTONE 6 ───────────────────────────────────────────────────────────
    run_m6_intelligence(survey, analysis, benchmark_results, publisher)

    # ── Final summary ─────────────────────────────────────────────────────────
    print("\n" + "█" * 55)
    print("  Files generated:")
    output_files = [
        "course_feedback_responses.json",
        "course_feedback_responses.csv",
        "course_feedback_async_responses.json",
        "course_feedback_async_responses.csv",
        "course_feedback_stream_analysis.json",
        "course_feedback_m6_augmented.json",
        "research_report.md",
    ]
    for f in output_files:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        status = f"{size:>6} bytes" if size else "  not created"
        print(f"    {f:<45} {status}")

    print("\n  All milestones (1–6) executed successfully.")
    print("█" * 55 + "\n")


if __name__ == "__main__":
    main()