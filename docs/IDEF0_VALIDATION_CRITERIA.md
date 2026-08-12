# IDEF0 Model Validation Criteria

This file lists the validation criteria derived from ISO/IEC/IEEE 31320-1:2012 for validating IDEF0 models.

Seven criteria are marked *(reviewer only)* and are not rows in the Verification Report. The four clause 6 rules turn on whether two things carry the same meaning, which no structural check can read. SYN-BOX-01, SYN-ARROW-02 and SYN-ARROW-04 constrain how the editor draws, and it can only draw one way, so the model holds nothing to inspect. Every remaining criterion is inspected and answered PASS or FAIL.

| ID | Location | Description |
|---|---|---|
| SYN-BOX-01 | 5.1 | *(reviewer only)* A box shall be a rectangle with square corners. |
| SYN-BOX-02 | 5.1 | A box name shall be an active verb or verb phrase fully contained within box boundaries. |
| SYN-BOX-05 | 5.4 | An unconnected box may not appear in a diagram. |
| SYN-BOX-03 | 5.1, 10.1 | A box shall contain a unique box number (0-9) in its lower right corner. |
| SYN-BOX-04 | 5.1 | If detailed by a child diagram, the box number shall be framed (box detail reference). |
| SYN-ARROW-01 | 5.2 | Arrows shall be drawn as straight horizontal and vertical lines; no diagonal lines allowed. |
| SYN-ARROW-02 | 5.2 | *(reviewer only)* Horizontal and vertical segments of an arrow shall be connected by a 90-degree curved arc. |
| SYN-ARROW-03 | 5.2, 5.3 | Every arrow segment shall have a noun or noun phrase label unless one label clearly applies to the whole arrow. |
| SYN-ARROW-04 | 5.2 | *(reviewer only)* A squiggle shall link arrow segments to labels unless the relationship is visually obvious. |
| SYN-ID-01 | 5.3 | Identifiers (names/labels) shall contain only alphanumeric characters, spaces, and hyphens (Title Case recommended). |
| SYN-ID-02 | 5.3 | Box names shall not contain the words 'function', 'activity', or 'process'. |
| SYN-ID-03 | 5.3 | Arrow labels shall not consist solely of 'input', 'control', 'output', 'mechanism', 'call', 'object', or 'data'. |
| SYN-ID-04 | 5.3 | No identifiers for different arrows or boxes shall be identical. |
| SYN-ATTACH-01 | 5.4 | At least one control arrow and at least one output arrow shall be attached to every box. |
| SYN-ATTACH-02 | 5.5 | Only one call arrow may be attached to a box. |
| SYN-ATTACH-03 | 5.4 | An arrow's type shall be the role it is drawn in: leaving a box makes it that box's output, entering one makes it that box's input/control/mechanism, and a leg merging into a bundle is the same kind as the bundle. |
| SEM-TRANS-01 | 6.1 | *(reviewer only)* Input must be transformed by the function into output; control and mechanism are not transformed. |
| SEM-TRANS-02 | 6.1 | *(reviewer only)* Output must account for all input, and all input must be accounted for by output. |
| SEM-JUNCT-01 | 6.2 | *(reviewer only)* Conservation of meaning: The meaning of a root segment must be equivalent to the union of meanings of segments that join/branch from it. |
| SEM-AMBIG-01 | 6.4, 6.5 | *(reviewer only)* Ambiguous arrow segments or attachments (implying multiple meanings) must be explicitly labeled. |
| DIA-COMP-01 | 7.2 | An IDEF0 model must include a required A-0 context diagram with exactly one box (Box 0). |
| DIA-COMP-02 | 7.2 | The A-0 diagram must present model name, abbreviation, viewpoint, and purpose. |
| DIA-COMP-03 | 9.1 | Except for A-0, a diagram shall contain a minimum of 2 and a maximum of 9 boxes. |
| DIA-PAGE-01 | 8.1, 8.2 | Each diagram must be on a separate page and be accompanied by at least one text page describing it. |
| DIA-GLOS-01 | 8.3 | Every arrow label and leaf-node box name must be defined in the glossary. |
| FEAT-CONN-01 | 9.2 | Every box in a diagram must be connected to at least one control boundary arrow and one output boundary arrow. |
| FEAT-BND-01 | 9.3 | Boundary arrows in a child diagram must correspond one-to-one with arrow segments attached to the parent box. |
| FEAT-TUN-01 | 9.4 | Tunneled arrows (using parentheses notation) shall traverse at least one diagram before reappearing. |
| REF-NODE-01 | 10.2 | Node numbers must be unique and follow the hierarchy (e.g., A1, A11, A111). |
