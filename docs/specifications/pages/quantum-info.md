# Quantum mechanics information specification

## Route and access

- `/decision/info` is a private level-3 child of `/decision`. Its back link points to the decision page, not directly to the dashboard.

## Content

- Explains that the suggestion uses an external random result and does not represent destiny, a binding decision, or proof of branching universes.
- Summarizes quantum fluctuations and the many-worlds interpretation, identifying the latter as an interpretation without definitive consensus.
- Explains the IBM Quantum one-qubit Hadamard measurement and includes sources from IBM Quantum and the Stanford Encyclopedia of Philosophy.
- This is informational content; it does not call APIs or persist data.

## Related files

`app/main/routes.py` (`quantum_info`), `app/templates/quantum_info.html`.
