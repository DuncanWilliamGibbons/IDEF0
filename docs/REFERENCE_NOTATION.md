# IDEF0 Reference Notation

This document describes the implementation of reference notation in accordance with ISO/IEC/IEEE 31320-1.

## Section 11: Arrow Reference Notation

According to Clause 11 of the standard, arrows and their connection points are referenced using ICOM codes. This section details the implementation of these codes and the reference expressions used in the software.

### 11.1 ICOM Code Components (Table 4)

The software implements ICOM codes as defined in Table 4 of ISO/IEC/IEEE 31320-1. Each code consists of a role-identifying letter followed by an integer index.

| Role | Letter | Description |
| :--- | :--- | :--- |
| **Input** | I | Arrows entering the left side of a functional box. |
| **Control** | C | Arrows entering the top side of a functional box. |
| **Output** | O | Arrows leaving the right side of a functional box. |
| **Mechanism** | M | Arrows entering the bottom side of a functional box. |
| **Call** | Call | Specific mechanism arrow used for external referencing. |

### 11.2 Boundary ICOM Codes

For boundary arrows (arrows entering or leaving a decomposition diagram that correspond to arrows on the parent box), the software automatically generates codes:

1.  **Inputs (I1, I2, ...)**: Numbered from top to bottom along the left boundary.
2.  **Controls (C1, C2, ...)**: Numbered from left to right along the top boundary.
3.  **Outputs (O1, O2, ...)**: Numbered from top to bottom along the right boundary.
4.  **Mechanisms (M1, M2, ...)**: Numbered from left to right along the bottom boundary.

### 11.3 Reference Expressions

The software supports the standard dot-notation for referring to diagram features:

*   **Syntax**: `[NodeNumber].[ICOM-Code]`
*   **Example**: `A2.C1` refers to the first Control arrow of Box A2.
*   **Example**: `A13.I2` refers to the second Input arrow of Box A13.

### 11.4 Implementation in Data Model

The `Arrow` class in `src/core/model.py` includes an `icom_code` field. This field is automatically populated by the `generate_icom_codes` utility, which sorts boundary arrows based on their spatial coordinates at the diagram edges.

---
