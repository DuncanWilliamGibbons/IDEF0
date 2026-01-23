# IDEF0
IDEF0 Modeler &amp; Functional Analysis 

This software allows the user to import, develop, and export IDEF0 models compliant with the ISO/IEC/IEEE 31320-1[^1] standard for functional modeling. The software has an intuitive GUI for the modeler to edit the model and visualize IDEF0 diagrams.

## Table of Contents
- [Description](#tensile-analyzer)
- [Features](#features)
- [Installation Instructions](#installation-instructions)
- [Data Format](#data-format)
- [Examples and Testing](#examples-and-testing)
- [License and Citation](#citation-and-license)
- [References](#references)
## Features
The IDEF0 program has the following features:
- Import and export IDEF0 models.
- Develop IDEF0-compliant models and diagrams.
- Editorial capabilities, including changing colors, fonts, font sizes, arrow styles, thicknesses, box sizes, and spacings.
## Installation Instructions
To run the IDEF0 program, the following prerequisite Python libraries must be installed:
```
pip install PyQt6, pytest, sys, os
```
After installing these prerequisites, the main_XXX.py (where XXX is the relevant version of the program) file can be run in your IDE of choice, and the GUI will appear.

## Data Format
An XML-based file format was developed to support the import and export of IDEF0 models. This file format is indicated by .idef0 and contains the functions, ICOMs, and editorial details to repeatably generate the IDEF0 model and associated diagrams. The program also had functionality to parse IDEF0 functional models into the new SysML V2 format per the OMG Systems Modeling Language™ (SysML®) Version 2.0[^2].

Supported data files that can be imported or exported from the IDEF0 software include:
- IDEF0 (.idef0)
- JSON (.json)
- SysML V2 (.sysml)
The following data formats are supported for exporting diagram views and plots:
- PDF (.pdf)
- SVG (.svg)
- PNG (.png)
- JPEG (.jpg)

## Examples and Testing

Tensile test data for 1045 Steel in the Normalized heat treatment conditions were used to test this program. The data used was obtained from the Materials Science and Engineering lab reports at the University of Illinois Urbana-Champaign[^5]. 3 test data files are in the "Test Data" folder and can be used to evaluate and experiment with the software. Below are some examples of the analyses and plots this software can perform.

<img src="Figures/Interface.png" alt="Interface" width="65%"> <img src="Figures/Data Export.png" alt="Data Export" width="25%">

<img src="Figures/Moduli.png" alt="Moduli" width="45%"> <img src="Figures/True Stress-Strain.png" alt="True Stress-Strain" width="45%">

<p align="center">
<img src="Figures/Ramberg.png" alt="Ramberg" width="65%">
</p>

## Citation and License
If you adapt or use this software, please refer to the CITATION.cff file for the citation style. This software can be cited as follows:

Gibbons, D. W. (2026). IDEF0 (Version 1.0) [Computer software]. 

MIT License

Copyright (c) 2026 Duncan W. Gibbons, Ph.D.

## References

[^1]: ISO. Information technology — Modeling Languages — Part 1: Syntax and Semantics for IDEF0. ISO/IEC/IEEE 31320-1, 2012.
[^2]: OMG. OMG Systems Modeling Language™ (SysML®) Version 2.0: Part 1: Language Specification. 2025.
