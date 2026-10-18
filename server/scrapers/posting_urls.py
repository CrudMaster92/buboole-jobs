"""Constrained posting URLs assembled from public listing identifiers."""

from string import Formatter
from urllib.parse import quote, urlsplit


def validate_template(template, allowed_hosts):
    if not isinstance(template, str) or len(template) > 4000:
        raise ValueError("posting URL template must be a bounded string")
    fields = []
    for _, field, spec, conversion in Formatter().parse(template):
        if field is not None:
            if field not in {"source_id", "url"} or spec or conversion:
                raise ValueError("posting URL template supports only source_id and url placeholders")
            fields.append(field)
    if not fields:
        raise ValueError("posting URL template needs an identifier placeholder")
    parsed = urlsplit(template)
    if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
            or parsed.username or parsed.password or parsed.fragment
            or "{" in parsed.netloc or "}" in parsed.netloc):
        raise ValueError("posting URL template must use HTTPS and a fixed allowed host")
    return fields


def render_template(template, allowed_hosts, **values):
    fields = validate_template(template, allowed_hosts)
    if any(values.get(field) in (None, "") for field in fields):
        return None
    encoded = {}
    for field in fields:
        value = values[field]
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return None
        # Dot-only path components would be normalized by HTTP clients.
        if str(value) in {".", ".."}:
            return None
        encoded[field] = quote(str(value), safe="")
    result = template.format(**encoded)
    parsed = urlsplit(result)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts or parsed.username or parsed.password:
        raise ValueError("posting URL template escaped the allowed host")
    return result
