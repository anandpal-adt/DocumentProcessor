import re


class PromptTemplate:
    """
    Utility class to make working with prompt templates easier, particularly in the presence of JSON.
    """

    def __init__(self, tmpl: str):
        self._raw = tmpl

    def render(self) -> str:
        escaped = self._raw.replace("{", "{{").replace("}", "}}")

        # Replace $feature with {feature}
        return re.sub(r"\$([A-Za-z0-9_-]+)", r"{\1}", escaped)
