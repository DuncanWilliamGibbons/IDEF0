# IDEF0 Modeler
[![GitHub All Releases](https://img.shields.io/github/downloads/DuncanWilliamGibbons/IDEF0/total.svg)](https://github.com/DuncanWilliamGibbons/IDEF0/releases) [![Views](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2FDuncanWilliamGibbons%2FIDEF0&count_bg=%2328a745&title_bg=%23555&style=for-the-badge&title=VIEWS)](https://hits.seeyoufarm.com)

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

<!-- [![Downloads](https://img.shields.io/github/downloads/DuncanWilliamGibbons/IDEF0/total?style=for-the-badge&color=28a745&logo=github)](https://github.com/DuncanWilliamGibbons/IDEF0/releases) -->

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
## Installation Instructions
To run the IDEF0 program, the following prerequisite Python libraries must be installed:
```
pip install PyQt6, pytest, sys, os
```
After installing these prerequisites, the main_XXX.py (where XXX is the relevant version of the program) file can be run in your IDE of choice, and the GUI will appear.
## Code Structure


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

## Examples and Testing
The program was demonstrated and tested using the Powder Bed Fusion (PBF) Reference Activity Model published in the NIST AMS 100-60 report[^4].

<!--  <img src="Figures/Interface.png" alt="Interface" width="65%"> <img src="Figures/Data Export.png" alt="Data Export" width="25%"> -->

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

