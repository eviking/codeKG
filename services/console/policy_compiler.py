"""
Policy compiler — translates natural language architectural constraints into
Cypher queries that return violating nodes.

No LLM is used. Compilation works by matching the NL statement against a set of
known constraint patterns using regex. When a pattern matches, the captured
groups are substituted into a Cypher template.

The architect sees the compiled Cypher in the UI before activating the policy
and can edit it directly if the auto-compilation is wrong.

Pattern library — extend this as needed:
  - cross-module call restrictions
  - layer restrictions (e.g. controller must not call repository directly)
  - annotation requirements (e.g. all service classes must have @Service)
  - inheritance restrictions
  - naming conventions
"""
from __future__ import annotations

import re


# Each entry: (compiled_regex, cypher_template_with_named_groups)
# The Cypher template must return rows with a `fqn` column for violators.
PATTERNS: list[tuple[re.Pattern, str]] = [

    # "X module must not directly call Y module"
    # "services in X must not call Y"
    (
        re.compile(
            r"(?:services?\s+in\s+|classes?\s+in\s+)?['\"]?(?P<src>\w+)['\"]?\s+module\s+"
            r"must\s+not\s+(?:directly\s+)?call\s+['\"]?(?P<tgt>\w+)['\"]?",
            re.IGNORECASE,
        ),
        """
MATCH (src:Class)-[:IMPORTS|CALLS*1..3]->(tgt:Class)
WHERE src.module = '{src}' AND tgt.module = '{tgt}'
RETURN DISTINCT src.fqn AS fqn
        """.strip(),
    ),

    # "X layer must not depend on Y layer"
    (
        re.compile(
            r"['\"]?(?P<src>\w+)['\"]?\s+layer\s+must\s+not\s+depend\s+on\s+['\"]?(?P<tgt>\w+)['\"]?",
            re.IGNORECASE,
        ),
        """
MATCH (src:Class)-[:IMPORTS]->(tgt:Class)
WHERE src.module = '{src}' AND tgt.module = '{tgt}'
RETURN DISTINCT src.fqn AS fqn
        """.strip(),
    ),

    # "All classes in X module must have annotation @Y"
    (
        re.compile(
            r"all\s+classes?\s+in\s+['\"]?(?P<module>\w+)['\"]?\s+module\s+must\s+have\s+"
            r"annotation\s+@?(?P<annotation>\w+)",
            re.IGNORECASE,
        ),
        """
MATCH (c:Class)
WHERE c.module = '{module}' AND NOT '@{annotation}' IN c.annotations
  AND NOT '{annotation}' IN [a IN c.annotations | replace(a, '@', '')]
RETURN c.fqn AS fqn
        """.strip(),
    ),

    # "Controllers must not directly call repositories"
    (
        re.compile(
            r"(?P<src>controller)s?\s+must\s+not\s+(?:directly\s+)?call\s+(?P<tgt>repositor(?:y|ies))",
            re.IGNORECASE,
        ),
        """
MATCH (src:Class)-[:IMPORTS|CALLS*1..2]->(tgt:Class)
WHERE toLower(src.name) CONTAINS 'controller' AND toLower(tgt.name) CONTAINS 'repository'
RETURN DISTINCT src.fqn AS fqn
        """.strip(),
    ),

    # "Service classes must not extend X"
    (
        re.compile(
            r"service\s+classes?\s+must\s+not\s+extend\s+['\"]?(?P<parent>\w+)['\"]?",
            re.IGNORECASE,
        ),
        """
MATCH (src:Class)-[:EXTENDS]->(parent {{name: '{parent}'}})
WHERE toLower(src.name) CONTAINS 'service'
RETURN src.fqn AS fqn
        """.strip(),
    ),

    # "All public methods in X must be annotated with @Y"
    (
        re.compile(
            r"all\s+public\s+methods?\s+in\s+['\"]?(?P<module>\w+)['\"]?\s+must\s+(?:be\s+)?annotated\s+with\s+@?(?P<annotation>\w+)",
            re.IGNORECASE,
        ),
        """
MATCH (c:Class)-[:CONTAINS]->(m:Method)
WHERE c.module = '{module}' AND 'public' IN m.modifiers
  AND NOT '@{annotation}' IN m.annotations
  AND NOT '{annotation}' IN [a IN m.annotations | replace(a, '@', '')]
RETURN m.fqn AS fqn
        """.strip(),
    ),
]


def compile_policy(natural_language: str) -> str:
    """
    Attempt to compile a natural language policy statement into a Cypher query.
    Returns the Cypher string, or a placeholder if no pattern matched.
    The architect can edit the Cypher directly in the UI.
    """
    nl = natural_language.strip()

    for pattern, template in PATTERNS:
        m = pattern.search(nl)
        if m:
            groups = m.groupdict()
            try:
                return template.format(**groups)
            except KeyError:
                continue

    # No pattern matched — return a commented placeholder the architect must fill in
    return f"""// Could not auto-compile: "{nl}"
// Please write a Cypher query that returns violating nodes as `fqn`:
//
// MATCH (c:Class) WHERE ... RETURN c.fqn AS fqn
"""
