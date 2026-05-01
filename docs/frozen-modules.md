# Frozen Modules

Frozen modules are implementation areas that have been approved as stable. They may be read, imported, and tested by other modules, but they cannot be modified without explicit approval from the Architect Agent or the project owner.

## Rule

- Read/import access is allowed.
- Test coverage may reference frozen modules.
- Behavioral changes, public API changes, file moves, and dependency changes are prohibited without approval.
- Emergency fixes must document the reason, affected contract, and reviewer approval in the changelog.

## Current Frozen Modules

No modules are frozen yet.

## Freezing Process

1. The Builder Agent proposes a module for freezing after implementation and tests are stable.
2. The Reviewer Agent verifies contracts, behavior, and test coverage.
3. The Architect Agent records the frozen status in this document.
