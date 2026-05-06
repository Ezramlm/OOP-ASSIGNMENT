"""

  Survey Data Processing System
  Course Feedback Survey (University Students)
  Milestones 3 & 4 — Evolved from Milestones 1 & 2


MILESTONE 3 ADDITIONS:
  - Advanced data structures (lists, dicts, sets, deque queue)
  - Higher-order functions (filter_responses, map, reduce)
  - Generators / iterators (response_generator, analysis_stream)
  - File-based persistence (JSON + CSV I/O pipeline)
  - Functional data pipeline (DataProcessor class)

MILESTONE 4 ADDITIONS:
  - Custom exception hierarchy (SurveyError, ValidationError,
    PersistenceError, AnalysisError)
  - Strategy design pattern  (ExportStrategy → JSON / CSV)
  - Observer design pattern  (SurveyEventPublisher + listeners)
  - Exception-safe wrappers throughout
  - Refactored & documented architecture

WHAT CHANGED FROM M1/M2:
  - Question.ask() now raises ValidationError instead of looping silently
  - Survey.conduct() catches ValidationError and retries gracefully
  - DataAnalyzer replaced by RobustDataAnalyzer (Strategy pattern)
  - Added DataProcessor with functional pipeline (filter, map, reduce)
  - Added SurveyEventPublisher + ConsoleSurveyLogger (Observer pattern)
  - Added JSON and CSV export strategies with PersistenceError handling
  - Generators added: Survey.response_generator(), DataProcessor.analysis_stream()
  - deque used as a response queue for ordered FIFO processing

WHAT FAILED & HOW IT WAS FIXED:
  - Problem: Plain print-and-loop validation mixed control + presentation.
    Fix: Raised ValidationError; Survey.conduct() handles it cleanly.
  - Problem: DataAnalyzer directly opened files — no error handling.
    Fix: Wrapped all I/O in try/except, raising PersistenceError on failure.
  - Problem: Single monolithic export block — hard to extend.
    Fix: Strategy pattern lets new formats be added without touching core code.
  - Problem: No event system — side effects buried inside methods.
    Fix: Observer pattern decouples logging/notification from core Survey logic.
"""

import json
import csv
import os
from abc import ABC, abstractmethod
from collections import deque
from functools import reduce
from datetime import datetime


# MILESTONE 4: CUSTOM EXCEPTION HIERARCHY


class SurveyError(Exception):
    """Base class for all survey-related errors."""
    pass


class ValidationError(SurveyError):
    """Raised when a user's answer fails validation rules."""
    pass


class PersistenceError(SurveyError):
    """Raised when data cannot be saved or loaded from disk."""
    pass


class AnalysisError(SurveyError):
    """Raised when analysis cannot be performed (e.g., no responses)."""
    pass



# MILESTONE 4: OBSERVER DESIGN PATTERN


class SurveyEventListener(ABC):
    """Abstract observer that reacts to survey lifecycle events."""

    @abstractmethod
    def on_response_recorded(self, respondent_number: int, response: dict):
        pass

    @abstractmethod
    def on_survey_complete(self, total_responses: int):
        pass

    @abstractmethod
    def on_export(self, filename: str, format_name: str):
        pass


class ConsoleSurveyLogger(SurveyEventListener):
    """Concrete observer: logs events to the console with timestamps."""

    def on_response_recorded(self, respondent_number: int, response: dict):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [LOG {ts}] Respondent {respondent_number} recorded "
              f"({len(response)} answers).")

    def on_survey_complete(self, total_responses: int):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [LOG {ts}] Survey complete — {total_responses} total response(s).")

    def on_export(self, filename: str, format_name: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [LOG {ts}] Export triggered → '{filename}' [{format_name}].")


class SurveyEventPublisher:
    """
    MILESTONE 4 – Observer Pattern.
    Maintains a list of listeners and broadcasts events to all of them.
    """

    def __init__(self):
        self._listeners: list[SurveyEventListener] = []

    def subscribe(self, listener: SurveyEventListener):
        self._listeners.append(listener)

    def unsubscribe(self, listener: SurveyEventListener):
        self._listeners.remove(listener)

    def notify_response_recorded(self, respondent_number: int, response: dict):
        for listener in self._listeners:
            listener.on_response_recorded(respondent_number, response)

    def notify_survey_complete(self, total_responses: int):
        for listener in self._listeners:
            listener.on_survey_complete(total_responses)

    def notify_export(self, filename: str, format_name: str):
        for listener in self._listeners:
            listener.on_export(filename, format_name)



# MILESTONE 4: STRATEGY DESIGN PATTERN (Export)


class ExportStrategy(ABC):
    """Abstract Strategy for exporting survey data."""

    @property
    @abstractmethod
    def format_name(self) -> str:
        pass

    @abstractmethod
    def export(self, data: list[dict], filename: str):
        """
        Export data to disk.
        Raises:
            PersistenceError: if the write operation fails.
        """
        pass


class JSONExportStrategy(ExportStrategy):
    """Concrete Strategy: exports data as a formatted JSON file."""

    @property
    def format_name(self) -> str:
        return "JSON"

    def export(self, data: list[dict], filename: str):
        path = f"{filename}.json"
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            print(f"  ✔ Saved → '{path}'")
        except IOError as e:
            raise PersistenceError(f"JSON export failed for '{path}': {e}") from e


class CSVExportStrategy(ExportStrategy):
    """Concrete Strategy: exports data as a CSV file."""

    @property
    def format_name(self) -> str:
        return "CSV"

    def export(self, data: list[dict], filename: str):
        if not data:
            raise PersistenceError("No data to export — CSV file was not created.")
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



# QUESTION CLASSES (Milestone 1 & 2 base, M3/M4 enhanced)


class Question(ABC):
    """Abstract base class for a survey question."""

    def __init__(self, text: str):
        self.text = text

    @abstractmethod
    def ask(self) -> str:
        """
        Prompt the user and return a validated answer.
        Raises:
            ValidationError: if the answer fails validation.
        """
        pass


class MultipleChoiceQuestion(Question):
    """Restricts the user to a predefined list of options."""

    def __init__(self, text: str, options: list[str]):
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
            raise ValidationError(
                f"'{raw}' is not a valid number. Choose 1–{len(self.options)}."
            )
        if not (1 <= choice <= len(self.options)):
            raise ValidationError(
                f"Choice {choice} is out of range. Choose 1–{len(self.options)}."
            )
        return self.options[choice - 1]


class RatingQuestion(Question):
    """Collects a numeric rating within a defined scale."""

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
            raise ValidationError(
                f"Rating must be between {self.min_val} and {self.max_val}."
            )
        return f"{rating} / {self.max_val}"


class TextQuestion(Question):
    """Accepts free-form text with a minimum length requirement."""

    def __init__(self, text: str, min_length: int = 5):
        super().__init__(text)
        self.min_length = min_length

    def ask(self) -> str:
        print(f"\n{self.text}")
        answer = input("Your response: ").strip()
        if len(answer) < self.min_length:
            raise ValidationError(
                f"Response too short — minimum {self.min_length} characters required."
            )
        return answer


# SURVEY CLASS (M1/M2 base + M3 generator + M4 observer)


class Survey:
    """
    Manages a collection of questions and respondent answers.

    Milestone 3 addition: response_generator() — memory-efficient iterator.
    Milestone 4 addition: publishes lifecycle events via SurveyEventPublisher.
    """

    def __init__(self, title: str, publisher: SurveyEventPublisher = None):
        self.title = title
        self.questions: list[Question] = []
        # MILESTONE 3: deque used as an ordered FIFO queue for responses
        self._response_queue: deque = deque()
        self.publisher = publisher or SurveyEventPublisher()

    def add_question(self, question: Question):
        self.questions.append(question)

    # MILESTONE 3: Generator — yields responses one at a time
  
    def response_generator(self):
        """Yields each collected response dict without loading all into memory."""
        for resp in self._response_queue:
            yield resp

    @property
    def responses(self) -> list[dict]:
        """Expose the internal deque as a plain list for compatibility."""
        return list(self._response_queue)

    def conduct(self):
        """
        Run through all questions, retrying on ValidationError.
        Appends completed response to the deque and notifies observers.
        """
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
                    # MILESTONE 4: ValidationError caught; user is informed cleanly
                    print(f"  ⚠  Input Error: {e}  Please try again.")
        self._response_queue.append(response)
        respondent_number = len(self._response_queue)
        print(f"\n  ✔ Response #{respondent_number} recorded successfully.")
        # MILESTONE 4: Observer notified
        self.publisher.notify_response_recorded(respondent_number, response)

    def display_responses(self):
        """Print all collected responses to the console."""
        responses = self.responses
        if not responses:
            print("  No responses collected yet.")
            return
        print("\n" + "=" * 50)
        print("  COLLECTED RESPONSES")
        print("=" * 50)
        for i, response in enumerate(responses, 1):
            print(f"\n  Respondent {i}:")
            for question, answer in response.items():
                print(f"    • {question}:")
                print(f"      → {answer}")


# MILESTONE 3: FUNCTIONAL DATA PIPELINE


class DataProcessor:
    """
    Milestone 3 — Functional Data Pipeline.

    Provides higher-order functions (filter, map, reduce) and
    a generator-based streaming analysis pipeline over raw responses.
    """

    def __init__(self, responses: list[dict]):
        self.responses = responses

   
    # Higher-order function: filter
   
    def filter_responses(self, criteria_func) -> list[dict]:
        """
        Return only responses that satisfy criteria_func.
        Example:
            processor.filter_responses(lambda r: "Excellent" in r.values())
        """
        return list(filter(criteria_func, self.responses))

   
    # Higher-order function: map
   
    def extract_field(self, question_text: str) -> list[str]:
        """
        Map over responses to extract all answers for a given question.
        Uses a list comprehension (Milestone 3 requirement).
        """
        return [r[question_text] for r in self.responses if question_text in r]

    # Higher-order function: reduce
   
    def count_keyword(self, question_text: str, keyword: str) -> int:
        """
        Reduce the responses to a count of how many times
        a keyword appears in answers for a specific question.
        """
        answers = self.extract_field(question_text)
        return reduce(lambda acc, a: acc + (1 if keyword.lower() in a.lower() else 0),
                      answers, 0)

   
    # MILESTONE 3: Generator — streaming analysis pipeline
   
    def analysis_stream(self):
        """
        Generator that yields (question, answer_counts_dict) pairs
        one question at a time — memory-efficient for large datasets.
        """
        # Collect all unique question texts preserving order
        seen: set = set()
        question_order: list[str] = []
        for resp in self.responses:
            for q in resp:
                if q not in seen:
                    seen.add(q)
                    question_order.append(q)

        for question in question_order:
            counts: dict = {}
            for resp in self.responses:
                answer = resp.get(question)
                if answer:
                    counts[answer] = counts.get(answer, 0) + 1
            yield question, counts

    def get_summary(self) -> list[list]:
        """
        MILESTONE 3: List comprehension — extracts answer values for all responses.
        """
        return [list(r.values()) for r in self.responses]

    def unique_answers(self, question_text: str) -> set:
        """
        MILESTONE 3: Returns a set of unique answers for a given question.
        """
        return {r[question_text] for r in self.responses if question_text in r}



# MILESTONE 4: ROBUST DATA ANALYZER (Strategy + Observer)


class RobustDataAnalyzer:
    """
    Milestone 4 — Combines Strategy Pattern (export) with
    Observer Pattern (event publishing) for a clean, extensible analyzer.
    """

    def __init__(self, survey: Survey, publisher: SurveyEventPublisher = None):
        self.survey = survey
        self.publisher = publisher or survey.publisher
        # Default export strategy is JSON
        self._export_strategy: ExportStrategy = JSONExportStrategy()
        self._analysis_results: dict = {}

    def set_export_strategy(self, strategy: ExportStrategy):
        """
        MILESTONE 4: Strategy Pattern — swap export format at runtime.
        """
        self._export_strategy = strategy

    def analyze(self) -> dict:
        """
        Count answer frequencies for every question.
        Raises:
            AnalysisError: if there are no responses to analyze.
        """
        if not self.survey.responses:
            raise AnalysisError("Cannot analyze — no responses have been collected.")
        self._analysis_results = {}
        for response in self.survey.response_generator():   # uses M3 generator
            for question, answer in response.items():
                counts = self._analysis_results.setdefault(question, {})
                counts[answer] = counts.get(answer, 0) + 1
        return self._analysis_results

    def display_analysis(self):
        """Print a percentage breakdown of answers per question."""
        if not self._analysis_results:
            try:
                self.analyze()
            except AnalysisError as e:
                print(f"  ✘ Analysis Error: {e}")
                return
        print("\n" + "=" * 50)
        print("  ANALYSIS RESULTS")
        print("=" * 50)
        for question, counts in self._analysis_results.items():
            print(f"\n  {question}")
            total = sum(counts.values())
            for answer, count in sorted(counts.items(),
                                        key=lambda x: x[1], reverse=True):
                pct = (count / total) * 100
                bar = "█" * int(pct / 5)
                print(f"    {answer:<35} {count:>2} resp  ({pct:5.1f}%)  {bar}")

    def export_responses(self, filename: str = "course_feedback_responses"):
        """
        MILESTONE 4: Export raw responses using the active Strategy.
        Raises PersistenceError on failure; notifies observers on success.
        """
        try:
            self._export_strategy.export(self.survey.responses, filename)
            self.publisher.notify_export(
                filename, self._export_strategy.format_name
            )
        except PersistenceError as e:
            print(f"  ✘ Export failed: {e}")

    def export_analysis(self, filename: str = "course_feedback_analysis"):
        """Export the analysis results dict using the active Strategy."""
        if not self._analysis_results:
            try:
                self.analyze()
            except AnalysisError as e:
                print(f"  ✘ Cannot export analysis: {e}")
                return
        # Analysis results is a dict-of-dicts; flatten to list for CSV compat
        flat = [
            {"Question": q, "Answer": a, "Count": c, "Percentage": f"{(c/sum(d.values()))*100:.1f}%"}
            for q, d in self._analysis_results.items()
            for a, c in d.items()
        ]
        try:
            self._export_strategy.export(flat, filename)
            self.publisher.notify_export(
                filename, self._export_strategy.format_name
            )
        except PersistenceError as e:
            print(f"  ✘ Export failed: {e}")

    @classmethod
    def load_from_json(cls, filename: str) -> "RobustDataAnalyzer":
        """
        MILESTONE 3 & 4: Load previously saved responses from a JSON file.
        Raises:
            PersistenceError: if the file cannot be read or parsed.
        """
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

        # Reconstruct a survey shell with the loaded responses
        survey = Survey("Loaded Survey")
        for resp in data:
            survey._response_queue.append(resp)
        return cls(survey)


# MAIN PROGRAM


def build_survey(publisher: SurveyEventPublisher) -> Survey:
    """Build the Course Feedback Survey with all questions."""
    survey = Survey("University Course Feedback Survey", publisher)

    survey.add_question(MultipleChoiceQuestion(
        "How would you rate the course overall?",
        ["Excellent", "Good", "Average", "Poor"]
    ))
    survey.add_question(RatingQuestion(
        "Rate the instructor's teaching clarity",
        min_val=1, max_val=5
    ))
    survey.add_question(MultipleChoiceQuestion(
        "How would you rate the course materials?",
        ["Very Helpful", "Helpful", "Neutral", "Not Helpful"]
    ))
    survey.add_question(RatingQuestion(
        "Rate the difficulty level of the course",
        min_val=1, max_val=10
    ))
    survey.add_question(MultipleChoiceQuestion(
        "Did the course meet your expectations?",
        ["Strongly Agree", "Agree", "Neutral", "Disagree", "Strongly Disagree"]
    ))
    survey.add_question(MultipleChoiceQuestion(
        "How was the workload of this course?",
        ["Too Heavy", "Manageable", "Just Right", "Too Light"]
    ))
    survey.add_question(TextQuestion(
        "What did you enjoy most about the course?",
        min_length=5
    ))
    survey.add_question(TextQuestion(
        "What suggestions do you have for improvement?",
        min_length=5
    ))
    return survey


def collect_responses(survey: Survey, publisher: SurveyEventPublisher):
    """Prompt for the number of respondents and conduct the survey."""
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


def run_functional_pipeline(survey: Survey):
    """
    MILESTONE 3: Demonstrate the functional data pipeline features.
    """
    print("\n" + "=" * 50)
    print("  MILESTONE 3 — FUNCTIONAL PIPELINE DEMO")
    print("=" * 50)

    processor = DataProcessor(survey.responses)

    # 1. Higher-order filter: find "Excellent" overall ratings
    excellent = processor.filter_responses(
        lambda r: "Excellent" in r.values()
    )
    print(f"\n  [Filter] Respondents rating the course 'Excellent': {len(excellent)}")

    # 2. Higher-order filter: difficulty ratings of 7 or above
    hard = processor.filter_responses(
        lambda r: any(
            k == "Rate the difficulty level of the course"
            and int(v.split("/")[0].strip()) >= 7
            for k, v in r.items()
        )
    )
    print(f"  [Filter] Respondents rating difficulty ≥ 7: {len(hard)}")

    # 3. Set of unique overall ratings collected
    unique = processor.unique_answers("How would you rate the course overall?")
    print(f"  [Set]    Unique overall ratings received: {unique}")

    # 4. List comprehension summary
    summary = processor.get_summary()
    print(f"  [List]   Answer vectors collected: {len(summary)} row(s)")

    # 5. Generator-based streaming analysis
    print("\n  [Generator] Streaming through analysis results:")
    for question, counts in processor.analysis_stream():
        total = sum(counts.values())
        top_answer = max(counts, key=counts.get)
        top_pct = counts[top_answer] / total * 100
        short_q = question[:55] + "…" if len(question) > 55 else question
        print(f"    '{short_q}' → top: '{top_answer}' ({top_pct:.0f}%)")


def run_exports(analyzer: RobustDataAnalyzer, publisher: SurveyEventPublisher):
    """
    MILESTONE 4: Demonstrate the Strategy pattern by exporting in both formats.
    """
    print("\n" + "=" * 50)
    print("  MILESTONE 4 — EXPORT STRATEGIES")
    print("=" * 50)

    base = "course_feedback"

    # JSON export (default strategy)
    print("\n  [Strategy: JSON] Exporting raw responses…")
    analyzer.set_export_strategy(JSONExportStrategy())
    analyzer.export_responses(f"{base}_responses")

    print("\n  [Strategy: CSV] Exporting raw responses…")
    analyzer.set_export_strategy(CSVExportStrategy())
    analyzer.export_responses(f"{base}_responses")

    print("\n  [Strategy: JSON] Exporting analysis results…")
    analyzer.set_export_strategy(JSONExportStrategy())
    analyzer.export_analysis(f"{base}_analysis")

    print("\n  [Strategy: CSV] Exporting analysis results…")
    analyzer.set_export_strategy(CSVExportStrategy())
    analyzer.export_analysis(f"{base}_analysis")

    print(f"\n  Files written:")
    for ext in ("json", "csv"):
        for tag in ("responses", "analysis"):
            path = f"{base}_{tag}.{ext}"
            size = os.path.getsize(path) if os.path.exists(path) else 0
            print(f"    {path}  ({size} bytes)")


def main():
    print("\n" + "█" * 55)
    print("  STA 2240 — Survey Data Processing System")
    print("  Course Feedback Survey  |  Milestones 3 & 4")
    print("█" * 55)

    # ── Set up Observer ──────────────────────────────────────
    publisher = SurveyEventPublisher()
    logger = ConsoleSurveyLogger()
    publisher.subscribe(logger)

    # ── Build survey and collect data ──────────────────────
    survey = build_survey(publisher)
    collect_responses(survey, publisher)

    # ── Display raw responses ────────────────────────────────
    survey.display_responses()

    # ── Functional pipeline (Milestone 3) ────────────────────
    run_functional_pipeline(survey)

    # ── Robust analysis (Milestone 4) ────────────────────────
    analyzer = RobustDataAnalyzer(survey, publisher)
    try:
        analyzer.analyze()
    except AnalysisError as e:
        print(f"\n  ✘ Analysis Error: {e}")
        return

    analyzer.display_analysis()

    # ── Exports — both JSON and CSV via Strategy ─────────────
    run_exports(analyzer, publisher)

    # ── Demonstrate loading saved data back from JSON ─────────
    print("\n  [Load Test] Reloading responses from JSON file…")
    try:
        reloaded = RobustDataAnalyzer.load_from_json("course_feedback_responses")
        print(f"  ✔ Loaded {len(reloaded.survey.responses)} response(s) from disk.")
    except PersistenceError as e:
        print(f"  ✘ Load failed: {e}")

    print("\n" + "█" * 55)
    print("  All milestones executed successfully.")
    print("█" * 55 + "\n")


if __name__ == "__main__":
    main()