import json

DEFAULT_FILENAME = "Survey Data Processing"

# QUESTION CLASSES (Inheritance Hierarchy)

class Question:
    """Base class representing a generic survey question."""

    def __init__(self, text):
        self.text = text

    def ask(self):
        """Prompt the user and return a validated, non-empty answer."""
        while True:
            answer = input(self.text + ": ").strip()
            if answer:
                return answer
            print("Response cannot be empty. Please try again.")


class MultipleChoiceQuestion(Question):
    """A question that restricts the user to a predefined list of options."""

    def __init__(self, text, options):
        super().__init__(text)
        self.options = options

    def ask(self):
        """Display numbered options and return the selected one."""
        print("\n" + self.text)
        for i, option in enumerate(self.options, 1):
            print(f"  {i}. {option}")
        while True:
            try:
                choice = int(input("Choose option: "))
                if 1 <= choice <= len(self.options):
                    return self.options[choice - 1]
                print(f"Please choose a number between 1 and {len(self.options)}.")
            except ValueError:
                print("Invalid input. Please enter a number.")


class RatingQuestion(Question):
    """A question that collects a numeric rating within a defined scale."""

    def __init__(self, text, min_val=1, max_val=5):
        super().__init__(text)
        self.min_val = min_val
        self.max_val = max_val

    def ask(self):
        """Prompt for a rating and return it as a formatted string."""
        print(f"\n{self.text} (Rate from {self.min_val} to {self.max_val})")
        while True:
            try:
                rating = int(input("Your rating: "))
                if self.min_val <= rating <= self.max_val:
                    return f"{rating} / {self.max_val}"
                print(f"Please enter a value between {self.min_val} and {self.max_val}.")
            except ValueError:
                print("Invalid input. Please enter a number.")


class TextQuestion(Question):
    """An open-ended question that accepts free-form text input."""

    def __init__(self, text, min_length=3):
        super().__init__(text)
        self.min_length = min_length

    def ask(self):
        """Prompt for a text response with a minimum character length."""
        print(f"\n{self.text}")
        while True:
            answer = input("Your response: ").strip()
            if len(answer) >= self.min_length:
                return answer
            print(f"Response must be at least {self.min_length} characters. Please elaborate.")


# SURVEY CLASS

class Survey:
    """Manages a collection of questions and stores respondent answers."""

    def __init__(self, title):
        self.title = title
        self.questions = []
        self.responses = []

    def add_question(self, question):
        """Add a question object to the survey."""
        self.questions.append(question)

    def conduct(self):
        """Run through all questions once and record the response."""
        response = {}
        print(f"\n--- {self.title} ---")
        for q in self.questions:
            response[q.text] = q.ask()
        self.responses.append(response)
        print("\n✔ Response recorded successfully.")

    def display_responses(self):
        """Print all collected responses to the console."""
        if not self.responses:
            print("No responses collected yet.")
            return
        print("\n========== Collected Responses ==========")
        for i, response in enumerate(self.responses, 1):
            print(f"\nRespondent {i}:")
            for question, answer in response.items():
                print(f"  {question}: {answer}")


# DATA ANALYZER CLASS

class DataAnalyzer:
    """Analyzes survey responses and produces frequency/percentage summaries."""

    def __init__(self, responses):
        self.responses = responses
        self.analysis_results = {}

    @classmethod
    def from_file(cls, filename):
        """Load previously saved responses from a JSON file."""
        with open(filename, "r") as f:
            return cls(json.load(f))

    def analyze(self):
        """Count occurrences of each answer for every question."""
        self.analysis_results = {}
        for response in self.responses:
            for question, answer in response.items():
                counts = self.analysis_results.setdefault(question, {})
                counts[answer] = counts.get(answer, 0) + 1
        return self.analysis_results

    def display_analysis(self):
        """Print a percentage breakdown of answers. Auto-analyzes if needed."""
        if not self.analysis_results:
            self.analyze()
        print("\n========== Analysis Results ==========")
        for question, counts in self.analysis_results.items():
            print(f"\n{question}")
            total = sum(counts.values())
            for answer, count in counts.items():
                percentage = (count / total) * 100
                print(f"  {answer}: {count} response(s) ({percentage:.1f}%)")

    def save_analysis(self, filename=DEFAULT_FILENAME):
        """Save the analysis results to a JSON file."""
        if not self.analysis_results:
            self.analyze()
        with open(filename, "w") as f:
            json.dump(self.analysis_results, f, indent=4)
        print(f"\n✔ Analysis saved to '{filename}'")

    def save_responses(self, filename="responses.json"):
        """Save raw responses to a JSON file for later reloading."""
        with open(filename, "w") as f:
            json.dump(self.responses, f, indent=4)
        print(f"✔ Raw responses saved to '{filename}'")


# MAIN PROGRAM

def main():
    #Build the survey
    survey = Survey("Course Feedback Survey")

    survey.add_question(MultipleChoiceQuestion(
        "Rate the course overall",
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

    survey.add_question(TextQuestion(
        "What did you enjoy most about the course?",
        min_length=5
    ))

    survey.add_question(TextQuestion(
        "What suggestions do you have for improvement?",
        min_length=5
    ))

    #Collect respondents
    while True:
        try:
            num_respondents = int(input("\nHow many respondents? "))
            if num_respondents > 0:
                break
            print("Please enter a positive number.")
        except ValueError:
            print("Invalid input. Please enter a whole number.")

    for i in range(num_respondents):
        print(f"\n>>> Respondent {i + 1} of {num_respondents}")
        survey.conduct()

    #Display and analyze
    survey.display_responses()

    analyzer = DataAnalyzer(survey.responses)
    analyzer.display_analysis()
    analyzer.save_analysis()
    analyzer.save_responses()


if __name__ == "__main__":
    main()
