"""Validate both exported formats, references, and embedded request/response examples."""

from pathlib import Path
import json

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate_spec
import yaml

OUTPUT = Path(__file__).resolve().parent


def main():
    document = json.loads((OUTPUT / "openapi.json").read_text(encoding="utf-8"))
    other = yaml.safe_load((OUTPUT / "openapi.yaml").read_text(encoding="utf-8"))
    if document != other:
        raise ValueError("JSON and YAML specifications differ")
    validate_spec(document)
    validate_spec(other)
    checked = 0

    def check(schema, example, location):
        nonlocal checked
        # Component references in nested schemas remain relative to this root.
        root = {"components": document["components"], "allOf": [schema]}
        error = next(Draft202012Validator(root).iter_errors(example), None)
        if error:
            raise ValueError(f"Invalid example at {location}: {error.message}")
        checked += 1

    def schema_examples(schema, location):
        if not isinstance(schema, dict):
            return
        for index, example in enumerate(schema.get("examples", [])):
            check(schema, example, f"{location}/examples/{index}")
        for field, child in schema.get("properties", {}).items():
            schema_examples(child, f"{location}/properties/{field}")
        if isinstance(schema.get("items"), dict):
            schema_examples(schema["items"], f"{location}/items")
        for keyword in ("anyOf", "oneOf", "allOf"):
            for index, child in enumerate(schema.get(keyword, [])):
                schema_examples(child, f"{location}/{keyword}/{index}")

    for name, schema in document["components"]["schemas"].items():
        schema_examples(schema, f"components/schemas/{name}")
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method not in {"get", "post", "patch", "put", "delete", "head", "options", "trace"}:
                continue
            containers = [("requestBody", operation.get("requestBody", {}))]
            containers.extend((f"responses/{status}", response)
                              for status, response in operation["responses"].items())
            for label, container in containers:
                for media, content in container.get("content", {}).items():
                    location = f"{method.upper()} {path}/{label}/{media}"
                    schema = content["schema"]
                    if "example" in content:
                        check(schema, content["example"], location)
                    for name, example in content.get("examples", {}).items():
                        if "value" in example:
                            check(schema, example["value"], f"{location}/{name}")
                    schema_examples(schema, location)
    print(f"Both documents pass OpenAPI validation; {checked} embedded examples pass JSON Schema validation.")


if __name__ == "__main__":
    main()
