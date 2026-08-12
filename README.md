# IDEF0 Modeler
<p align="center">
  <img src="Documents/Logo/logo_full.png" alt="IDEF0 Modeler" width="420">
</p>

<p align="center">
  A desktop editor for IDEF0 function models that draws, checks and exports them
  to the conformance rules of <b>ISO/IEC/IEEE 31320-1:2012</b>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.9.0-blue" alt="Version 0.9.0">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52" alt="PyQt6">
  <img src="https://img.shields.io/badge/standard-ISO%2FIEC%2FIEEE%2031320--1-004225" alt="ISO/IEC/IEEE 31320-1">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT licence">
</p>

[![DOI](https://zenodo.org/badge/1017644488.svg)](https://doi.org/) [![Views](https://api.visitorbadge.io/api/visitors?path=DuncanWilliamGibbons/IDEF0&label=Views&countColor=%23007ec6&style=flat)](https://github.com/DuncanWilliamGibbons/IDEF0) [![License](https://img.shields.io/github/license/DuncanWilliamGibbons/IDEF0?style=flat&color=blue)](https://github.com/DuncanWilliamGibbons/IDEF0/blob/main/LICENSE) [![Last Commit](https://img.shields.io/github/last-commit/DuncanWilliamGibbons/IDEF0?style=flat&color=orange)](https://github.com/DuncanWilliamGibbons/IDEF0/commits/main)


This software enables users to import, develop, and export Integrated Definition for Function Modeling (IDEF0) models that comply with the ISO/IEC/IEEE 31320-1[^1] standard for functional modeling. The software has an intuitive GUI for the modeler to edit the model and visualize IDEF0 diagrams. 

The IDEF0 modeling language has its roots in the Structured Analysis and Design Technique (SADT). It was developed for the US Air Force and formalized by the NIST FIBS PUB 183 specification in 1993 [^2]. This modeling language and approach are simple and easy to understand by stakeholders, while also enabling the modeling of large and complex functional architectures of systems or enterprises. This can be in the form of software functions, operating processes, or general activities. This language and approach are not as popular as they once were, largely due to the lack of vendor and tool support, model-based and digital formats, and integration or links to other modeling and information formats. This software aims to address these shortcomings by providing a simple GUI to model IDEF0-compliant functional models and architectures, developing an XML-based data format, and the capability to parse the models into other useful formats, such as SysML V2 or JSON files for further development and integrations with other model-based systems engineering (MBSE) tools and systems.

## Table of Contents
- [Description](#tensile-analyzer)
- [Features](#features)
- [Installation Instructions](#installation-instructions)
- [Code Structure](#code-structure)
- [Data Format](#data-format)
- [Examples and Testing](#examples-and-testing)
- [License and Citation](#citation-and-license)
- [References](#references)
## Features
The IDEF0 program has the following features:
- Import and export IDEF0 models.
- Develop IDEF0-compliant models and diagrams.
- Editorial capabilities, including changing colors, fonts, font sizes, arrow styles, thicknesses, box sizes, and spacings.

- **Full IDEF0 syntax** — function boxes with node numbers and detail references,
  ICOM arrows on all four faces, call arrows, boundary arrows, branches and
  merges with junction dots, tunnelled arrows, and the A-0 context diagram with
  its purpose and viewpoint statements.
- **Hierarchical decomposition** — double-click a box to open or create its child
  diagram; boundary arrows stay reconciled with the parent in both directions.
- **Automatic layout and routing** — diagonal box placement and orthogonal
  (Manhattan) arrow routing, computed from the model on every draw. Arrow order
  on each box face, label placement and trunk nesting each follow the rule that
  minimises crossings for that face; see [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md)
  for which rule and why.
- **Both ICOM identities, kept apart** — the code you assign (`P.2`, `D.4.1`) and
  the positional code the standard defines (`C1`, `O2`) live in separate fields.
  **View → ICOM IDs** picks which is drawn; both stay editable either way.
- **Verification report** — 22 criteria from ISO/IEC/IEEE 31320-1 evaluated
  against the model, each result saying how it was decided. Every row is PASS or
  FAIL; criteria no tool can decide are listed in
  [Documents/IDEF0_Validation_Criteria.md](Documents/IDEF0_Validation_Criteria.md)
  for a human reviewer rather than reported as passing.
- **Model database views** — ICOMs and Functions as filterable tables, each with
  an export button writing what the table currently shows as CSV, JSON, XML or TXT.
- **Reports** — node tree, node index, and a **flow report per ICOM role**
  listing every diagram that carries one, with the arrows named and counted.
  The flow reports filter, size to their text and export like the database
  views, and double-clicking a row opens that diagram.
- **Exports** — seven code and interchange formats (below), plus diagram export
  to PNG, JPEG, SVG or PDF.
  
## Installation Instructions
To run the IDEF0 program, the following prerequisite Python libraries must be installed:
```
pip install PyQt6, pytest, sys, os
```
After installing these prerequisites, the main_XXX.py (where XXX is the relevant version of the program) file can be run in your IDE of choice, and the GUI will appear.

Python 3.9 or newer, developed and tested on 3.13.

```bash
git clone https://github.com/<your-account>/idef0-modeler.git
cd idef0-modeler
pip install -r requirements.txt
```

The only runtime dependency is PyQt6; `pytest` is used for the test suite.

## Running

```bash
python src/main.py
```

The application opens on an empty A-0 context diagram. To see a real model
instead, use **File → Open Project** on one of the models in
[Example Model/](Example%20Model/):


### A first model

1. **Model → Add Function Box** on the A-0 diagram to create the single context
   box, then name it with a verb phrase.
2. **Model → Add Arrow** to attach its inputs, controls, outputs and mechanisms.
   The face an arrow attaches to is its role.
3. Double-click the box to decompose it. The parent's boundary arrows arrive on
   the child diagram as stubs to be connected to the child's boxes.
4. **Report → Verification Report (ISO 31320-1)** to see what the model does and
   does not yet satisfy.
5. **File → Save Project** writes a `.idefproj` file — the model with its layout.
   **File → Export IDEF0 Model** writes a `.idef0` file, which is the functional
   content alone with positions and colours stripped.
   
## Code Structure
The codebase is one split: **`src/core/` holds no Qt import**, and `src/gui/`
is where every `PyQt6` import lives. `src/core/` is the model, and everything
it does — parsing, layout, routing, conformance checking, exporting — is a pure
function of that model, checkable without a display. `src/gui/` is one drawing
of it; the diagram on screen is derived from `core` on every redraw, not the
other way around, which is what lets the same model exported to Python, UML and
BPMN never disagree with what the diagram shows.

```
src/main.py              MainWindow - menus, toolbars, undo history, wires GUI to core
│
├── src/core/             no PyQt import anywhere in this package
│   ├── model.py             the data model: IDEF0Model, Diagram, ActivityBox,
│   │                        Arrow, ArrowType, Point - everything else reads this
│   ├── layout.py            diagonal box placement, Manhattan arrow routing
│   ├── xml_io.py            model ⇄ .idefproj / .idef0 (the only serialisation)
│   ├── compliance.py        the 22 ISO/IEC/IEEE 31320-1 criteria the report runs
│   ├── export_common.py     resolves the model into an activity tree once,
│   │                        shared by every exporter below so they read one
│   │                        account of what the model says
│   └── {code,uml,sysml,plantuml,bpmn}_export.py
│                            one file per export target, each just a renderer
│                            of the tree export_common built
│
└── src/gui/              PyQt6 only; everything here reads src/core, nothing
    │                     in src/core reads this back
    ├── diagram_scene.py     QGraphicsScene subclass - lays out and routes a
    │                        Diagram from src.core.layout, then draws it
    ├── diagram_items.py     the QGraphicsItem subclasses layout draws:
    │                        boxes, arrows, labels, tunnel notation
    ├── management_views.py  ICOMs / Functions / Flow Report tables, the
    │                        filter+export machinery they share
    ├── verification_tab.py  runs src.core.compliance and renders the report
    ├── frame_item.py, item_panel.py, properties_panel.py, dialogs.py, theme.py
    │                        frame border, per-item editing panel, settings
    │                        panel, modal dialogs, the dark-mode stylesheet

tests/                    pytest suite, laid out to mirror src/ (below)
docs/                     design rationale and export mappings
Documents/                the IDEF0 standards, validation criteria, reference notation
Example Model/            reference models and the literature they come from
```

## Data Format
An XML-based file format was developed to support the import and export of IDEF0 models. This file format is indicated by .idef0 and contains the functions, ICOMs, and editorial details to repeatably generate the IDEF0 model and associated diagrams. The program also had functionality to parse IDEF0 functional models into the new SysML V2 format per the OMG Systems Modeling Language™ (SysML®) Version 2.0[^3].

Supported data files that can be imported or exported from the IDEF0 software include:
- IDEF0 (.idef0)
- JSON (.json)
- SysML V2 (.sysml)
- UML (.xmi & .puml)
- BPMN 2.0 (.bpmn)
  
The following data formats are supported for exporting diagram views, tabular data, and plots:
- PDF (.pdf)
- SVG (.svg)
- PNG (.png)
- JPEG (.jpg)
- JSON (.json)
- TEXT (.txt)
- CSV (.csv)

Functionality is included that parses the IDEF0 models to the following programming languages (requires further testing):
- Python
- Java
- C++

  ## Editing and history

Three commands govern the state of what you are looking at. They work at
different scopes, which is the thing to know about them:

| Command | Where | Scope | Undoable |
| :--- | :--- | :--- | :--- |
| **Undo** | Model menu | the whole project | — |
| **Reset Diagram** | Diagram Utilities panel | the active diagram | yes |
| **Refresh View** | Diagram Utilities panel | nothing — redraws only | n/a |

**Undo** steps the entire project model back to before the last recorded change.
Every command that alters the model takes a snapshot first, including edits and
deletions made in the ICOMs and Functions databases, so anything that changed
the model can be stepped back. Two consequences worth knowing: the history is
**five deep**, the oldest entry being dropped once it is full; and it is
**model-wide, not per-diagram**, so an undo of a change made on A2 is undone
while you are looking at A3. Opening or starting a project clears the history —
it belongs to the model it was recorded against.

**Reset Diagram** returns the active diagram to how it stood when its tab was
first opened with content in this session, discarding every box, arrow and
manual adjustment made to it since. It is itself undoable, so a reset in error
costs one Undo. On a diagram that has never held a box there is nothing recorded
to go back to, and it does nothing.

**Refresh View** re-runs layout and routing for every open diagram from the
model as it currently stands. It changes no data and takes no undo snapshot —
reach for it when the drawing and the model look out of step, not to alter
anything. **Model → Automatically Route Arrows** is the destructive relative:
it discards manual arrow segments, junctions and label offsets so everything is
routed afresh, and *is* undoable.

## Files

| Command | Writes | Contains |
| :--- | :--- | :--- |
| **File → Save Project** | `.idefproj` | the model **and its drawing** — box positions and sizes, routed arrow segments, junctions, colours, label offsets |
| **File → Open Project** | reads `.idefproj` or `.idef0` | replaces the open project and reopens at A-0 |
| **File → Export IDEF0 Model** | `.idef0` | the model **without the drawing** — boxes, arrows, types, labels, ICOM codes and attachments only |
| **File → Import IDEF0 Model** | reads `.idef0` | as above, then lays the model out automatically |
| **File → Export Diagram** | `.png` `.jpg` `.svg` `.pdf` | the active diagram as a picture |

Both formats are XML and both round-trip losslessly: saving a reopened project
reproduces the same file, so repeated save/open cycles cannot drift. Each file
records which build wrote it (`generator`, `generatorVersion` on the root
element), separately from the `<Version>` you set for the model itself.

The distinction between the two is **layout, not content** — a `.idef0` carries
every box and arrow, just no geometry. What decides whether a layout is applied
on open is the geometry in the file rather than its extension: a model whose
boxes all sit at the origin has no layout to preserve, so it is laid out
diagonally and routed afresh. A `.idefproj` saved from a model that was never
positioned therefore behaves like a functional import, which is intended.

An `Export` button on the ICOMs database, the Functions database and each Flow
Report writes **the rows currently shown**, filter included, as CSV, JSON, XML
or TXT.

## Exports

**File → Export Code Architecture** writes the functional architecture as:

| Target | Output | Mapping |
| :--- | :--- | :--- |
| Python | module that runs as it stands | one method per function, signals wired through a per-activity context |
| Java | class that compiles | as above |
| C++ | translation unit that compiles | as above |
| SysML v2 | textual notation | `action def` per function, ICOMs as `in`/`out` item features |
| UML | XMI 2.1 | `uml:Activity` per function, box → `CallBehaviorAction`, arrow → `ObjectFlow` between pins |
| UML | PlantUML activity diagrams | the same mapping, drawn — one page per diagram of the model |
| BPMN | BPMN 2.0 XML | leaf → `bpmn:task`, decomposition → `callActivity`, control/mechanism → `dataObjectReference` |

All seven read the model through `src/core/export_common.py`, which resolves it
once into an activity tree, so they cannot disagree about what the model says.
Every one of them exports the **whole project**, not the diagram in front of
you, and supplies its own extension if you do not type one.

Two decisions shape the UML and BPMN mappings, both explained in
[docs/EXPORTS.md](docs/EXPORTS.md): IDEF0 states no sequence, so boxes are laid
out in dependency tiers rather than chained into a false order; and an IDEF0
control is data that governs a function, so it maps to an object flow into a
pin, not to a UML control flow.

## Examples and Testing
The program was demonstrated and tested using the Powder Bed Fusion (PBF) Reference Activity Model published in the NIST AMS 100-60 report[^4].

<!--  <img src="Figures/Interface.png" alt="Interface" width="65%"> <img src="Figures/Data Export.png" alt="Data Export" width="25%"> -->

## Limitations and Future Work
- **Call arrows** are held in the model, validated (only one per box) and
  exported as mechanisms, but are drawn and routed like any other mechanism
  rather than with the dedicated geometry clause 5.5 describes.
- **Semantic criteria cannot be checked.** Whether an output truly accounts for
  its inputs, or a trunk means the union of its legs, asks whether two things
  carry the same meaning. Nothing here reads meaning, so those criteria are left
  to a human reviewer rather than reported on.
- **Glossary and text pages** (clause 8.3) are not yet editable in the
  application.

## Citation and License
If you adapt or use this software, please refer to the CITATION.cff file for the citation style. This software can be cited as follows:

Gibbons, D. W. (2026). IDEF0 Modeler (Version 0.9.0) [Computer software]. 

MIT License

Copyright (c) 2026 Duncan W. Gibbons, Ph.D.

## References

[^1]: ISO. Information technology — Modeling Languages — Part 1: Syntax and Semantics for IDEF0. ISO/IEC/IEEE 31320-1, 2012.
[^2]: NIST. Integrated Definition for Function Modeling (IDEF0). NIST FIBS PUB 183, 1993.
[^3]: OMG. OMG Systems Modeling Language™ (SysML®) Version 2.0: Part 1: Language Specification. 2025.
[^4]: Gibbons, D. W., & Witherell, P. W. A Reference Activity Model for Additive Manufacturing: Powder Bed Fusion (NIST AMS 100-60). https://doi.org/10.6028/NIST.AMS.100-60. 2024.

