"""
Case file loading, validation, listing, and image path resolution.
"""

import json
import os
from typing import Dict, List, Optional, Tuple

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from game_engine import CaseData


class CaseManager:

    def __init__(self, cases_dir: str, images_dir: str = None):
        self.cases_dir = os.path.abspath(cases_dir)
        self.images_dir = images_dir or os.path.join(self.cases_dir, "images")
        self._schema = self._load_schema()

    def _load_schema(self) -> Optional[Dict]:
        schema_path = os.path.join(self.cases_dir, "schema.json")
        if os.path.exists(schema_path):
            with open(schema_path, "r") as f:
                return json.load(f)
        return None

    def list_cases(self, difficulty: str = None, tag: str = None) -> List[Dict]:
        """List available cases with metadata for the selection screen."""
        cases = []
        for filename in sorted(os.listdir(self.cases_dir)):
            if not filename.endswith(".json") or filename == "schema.json":
                continue
            try:
                case_data = self.load_case(filename)
                meta = case_data.get("meta", {})
                case_info = case_data.get("case", {})

                if difficulty and meta.get("difficulty") != difficulty:
                    continue
                if tag and tag not in meta.get("tags", []):
                    continue

                slug = os.path.splitext(filename)[0]
                image = case_info.get("image", "")
                image_url = f"/cases/images/{image}" if image else ""

                cases.append({
                    "slug": slug,
                    "filename": filename,
                    "name": case_info.get("name", slug),
                    "summary": case_info.get("summary", case_info.get("description", "")[:120]),
                    "image": image_url,
                    "difficulty": meta.get("difficulty", "intermediate"),
                    "estimated_minutes": meta.get("estimated_minutes", 10),
                    "tags": meta.get("tags", []),
                    "evidence_count": len(case_data.get("evidence", [])),
                })
            except Exception:
                continue
        return cases

    def load_case(self, filename_or_slug: str) -> Dict:
        """Load raw case data from a JSON file."""
        if not filename_or_slug.endswith(".json"):
            filename_or_slug += ".json"
        path = os.path.join(self.cases_dir, filename_or_slug)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Case file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_case_data(self, filename_or_slug: str) -> CaseData:
        """Load and return a CaseData object for engine use."""
        raw = self.load_case(filename_or_slug)
        return CaseData(raw)

    def validate_case(self, filename_or_slug: str) -> Tuple[bool, str]:
        """Validate a case file against the schema."""
        try:
            raw = self.load_case(filename_or_slug)
        except FileNotFoundError as e:
            return False, str(e)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"

        if self._schema and HAS_JSONSCHEMA:
            try:
                jsonschema.validate(instance=raw, schema=self._schema)
            except jsonschema.ValidationError as e:
                return False, f"Schema validation failed: {e.message}"

        try:
            CaseData(raw)
        except ValueError as e:
            return False, str(e)

        return True, "Valid case file"

    def validate_all_cases(self) -> List[Dict]:
        """Validate all case files and return results."""
        results = []
        for filename in sorted(os.listdir(self.cases_dir)):
            if not filename.endswith(".json") or filename == "schema.json":
                continue
            is_valid, message = self.validate_case(filename)
            results.append({
                "filename": filename,
                "slug": os.path.splitext(filename)[0],
                "is_valid": is_valid,
                "message": message,
            })
        return results

    def get_case_image_path(self, image_filename: str) -> Optional[str]:
        """Resolve a case image filename to its absolute path."""
        if not image_filename:
            return None
        path = os.path.join(self.images_dir, image_filename)
        return path if os.path.exists(path) else None

    def get_full_case(self, slug: str) -> Dict:
        """Get full case data including resolved image path."""
        raw = self.load_case(slug)
        case_info = raw.get("case", {})
        image = case_info.get("image", "")
        if image:
            case_info["image_url"] = f"/cases/images/{image}"
        return raw
