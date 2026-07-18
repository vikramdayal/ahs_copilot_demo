# Phase 2 handoff used by the query engine

The Day 2 checkpoint established a normalized metadata package and a fail-closed boundary between candidate metadata and executable analysis. The execution-relevant contracts preserved here are:

- Logical source records exist for National/Metropolitan PUF household, PUF person, PUF mortgage, PUF projects, and corresponding IUF household/mortgage/projects relations.
- `CONTROL` is the housing-unit parent key. Mortgage and project files also have child sequence keys `MORTLINE` and `PROJECTNO`.
- Mortgage and project relations are one-to-many children. They must be aggregated to one row per `CONTROL` before household weights are applied.
- Physical CSV paths are runtime configuration, not semantic metadata.
- PUF and IUF access levels are explicit and may not be mixed implicitly.
- The LLM may propose typed objects but may not submit arbitrary SQL.
- Expressions, recodes, and unsupported relationships fail closed.

The original Day 2 checkpoint reported 21 tables, 388 variables, 2,338 universes, 11 recodes, eight source-file contracts, and 68 diagnostics. This Day 3 package consumes the source-file contracts and adds a small certified execution catalog for the household/mortgage/projects relationships.
