"""ResponseParser — LLM output → Raw Dict → Schema Validation → Dataclass.

Three-stage pipeline:
  1. parse_json(text) → extract JSON from LLM response (handles markdown code blocks)
  2. validate(raw_dict, schema) → check required fields, types, ranges
  3. to_dataclass(validated_dict) → convert to typed dataclass

Extra fields are silently ignored (future-proof). Missing required fields raise errors.
"""

import json
import re
from typing import Any


class ParseError(Exception):
    """LLM output could not be parsed."""
    pass


class ValidationError(Exception):
    """LLM output failed schema validation."""
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class ResponseParser:
    """Parse and validate LLM JSON responses.

    Usage:
        parser = ResponseParser()
        raw_dict = parser.parse_json(llm_text)
        validated = parser.validate(raw_dict, EXTRACTION_SCHEMA)
        candidate = parser.to_candidate(validated)
    """

    # ── Stage 1: Extract JSON from text ──────────────────────

    def parse_json(self, text: str) -> dict | list:
        """Extract and parse JSON from LLM response text.

        Handles:
          - Raw JSON: {"key": "value"}
          - Markdown code block: ```json ... ```
          - Array JSON: [{...}, {...}]
          - Text with embedded JSON object

        Raises:
            ParseError: If no valid JSON can be extracted.
        """
        if not text or not text.strip():
            raise ParseError("Empty LLM response")

        # Try 1: Markdown code block with json tag
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try 2: Find first { or [ and match to the end
        # Look for a JSON object (starts with {)
        obj_start = text.find("{")
        arr_start = text.find("[")
        if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
            return self._extract_balanced(text, obj_start, "{", "}")
        elif arr_start >= 0:
            return self._extract_balanced(text, arr_start, "[", "]")

        # Try 3: Raw parse entire text
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        raise ParseError(f"Cannot extract JSON from LLM response: {text[:200]}...")

    def _extract_balanced(self, text: str, start: int, open_c: str, close_c: str) -> dict | list:
        """Extract a balanced JSON structure starting at `start`."""
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == open_c:
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])

        raise ParseError(f"Unbalanced {open_c}{close_c} in LLM response")

    # ── Stage 2: Schema validation ────────────────────────────

    def validate(self, raw: dict, schema: dict) -> dict:
        """Validate a raw dict against a simple schema.

        Schema format:
        {
            "required": ["field1", "field2"],
            "properties": {
                "field1": {"type": "str", "min": 1, "max": 5000},
                "field2": {"type": "float", "min": 0.0, "max": 1.0},
                "field3": {"type": "list"},
            }
        }

        Extra fields in raw are silently ignored (forward-compatible).
        Missing required fields raise ValidationError.
        Type mismatches are coerced when safe, or raise ValidationError.

        Args:
            raw: Raw dict from LLM JSON.
            schema: Validation schema dict.

        Returns:
            Cleaned dict with only known properties (extra fields stripped).

        Raises:
            ValidationError: If validation fails.
        """
        errors: list[str] = []
        validated: dict[str, Any] = {}

        required = schema.get("required", [])
        properties = schema.get("properties", {})

        # Check required fields
        for field in required:
            if field not in raw or raw[field] is None:
                errors.append(f"Missing required field: {field}")

        if errors:
            raise ValidationError("Schema validation failed", errors)

        # Validate each property
        for field, prop_schema in properties.items():
            if field not in raw:
                if field in required:
                    errors.append(f"Missing required field: {field}")
                continue

            value = raw[field]
            try:
                validated[field] = self._validate_field(field, value, prop_schema)
            except ValueError as e:
                errors.append(str(e))

        if errors:
            raise ValidationError("Schema validation failed", errors)

        return validated

    def _validate_field(self, name: str, value: Any, schema: dict) -> Any:
        """Validate and coerce a single field value."""
        expected_type = schema.get("type", "str")

        if expected_type == "str":
            if not isinstance(value, str):
                value = str(value)
            min_len = schema.get("min", 0)
            max_len = schema.get("max", 100000)
            if len(value) < min_len:
                raise ValueError(f"Field '{name}': length {len(value)} < min {min_len}")
            if len(value) > max_len:
                # Truncate instead of failing
                value = value[:max_len]
            return value

        elif expected_type == "float":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"Field '{name}': cannot convert {value!r} to float")
            lo = schema.get("min", float("-inf"))
            hi = schema.get("max", float("inf"))
            return max(lo, min(hi, value))

        elif expected_type == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"Field '{name}': cannot convert {value!r} to int")
            lo = schema.get("min", -10**9)
            hi = schema.get("max", 10**9)
            return max(lo, min(hi, value))

        elif expected_type == "list":
            if isinstance(value, str):
                # Try parsing JSON string as list
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = [value]
            if not isinstance(value, list):
                value = [value]
            return value

        elif expected_type == "bool":
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "1")
            return bool(value)

        # Unknown type — pass through
        return value

    # ── Stage 3: Dict → Dataclass ─────────────────────────────

    def to_candidate(self, validated: dict) -> "MemoryCandidate":
        """Convert validated dict to MemoryCandidate."""
        from src.memory.intelligence.candidate import MemoryCandidate
        return MemoryCandidate(
            type=validated.get("type", "knowledge"),
            text=validated.get("text", ""),
            summary=validated.get("summary", ""),
            tags=validated.get("tags", []),
            estimated_importance=validated.get("estimated_importance", 0.5),
            confidence=validated.get("confidence", 0.5),
            reason=validated.get("reason", ""),
            source_quote=validated.get("source_quote", ""),
            source_message_index=validated.get("source_message_index", -1),
            candidate_type=validated.get("candidate_type", "fact"),
        )

    def to_decision(self, validated: dict) -> dict:
        """Convert validated dict to a generic strategy decision dict."""
        return {
            "decision": validated.get("decision", "distinct"),
            "reason": validated.get("reason", ""),
            "merged_text": validated.get("merged_text", ""),
            "merged_summary": validated.get("merged_summary", ""),
            "merged_tags": validated.get("merged_tags", []),
            "refined_summary": validated.get("refined_summary", ""),
            "refined_tags": validated.get("refined_tags", []),
            "split_parts": validated.get("split_parts", []),
        }
