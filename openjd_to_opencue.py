#!/usr/bin/env python3
"""
openjd_to_opencue.py
====================
A converter that takes Open Job Description (OpenJD) templates and turns
them into OpenCue render farm jobs.

Overview
--------
Open Job Description (OpenJD) is an open specification by AWS for defining
portable batch processing jobs in YAML or JSON. It was designed for VFX
render farms but is scheduler-agnostic.

OpenCue is an open-source render management system originally developed at
Sony Pictures Imageworks, now an Academy Software Foundation (ASWF) project.
It dispatches work across render farm hosts using its own internal job model.

This script bridges the two: you author jobs once in OpenJD's portable format,
and this converter translates them into OpenCue's native structure for
submission via PyOutline (OpenCue's Python job-building library).

No existing integration between these two projects exists — this is a
first-of-its-kind bridge.


Concept Mapping
---------------
The two systems model work similarly but use different terminology:

    ┌─────────────────────┐         ┌─────────────────────┐
    │      OpenJD          │         │      OpenCue         │
    ├─────────────────────┤         ├─────────────────────┤
    │ Job Template         │  ────►  │ Job (Outline)        │
    │   ├─ parameterDefs   │  ────►  │   (resolved at CLI)  │
    │   ├─ Step            │  ────►  │   ├─ Layer           │
    │   │   ├─ paramSpace  │  ────►  │   │   ├─ frame range │
    │   │   ├─ script      │  ────►  │   │   ├─ command     │
    │   │   ├─ hostReqs    │  ────►  │   │   ├─ resources   │
    │   │   └─ dependencies│  ────►  │   │   └─ depend_on() │
    │   └─ Step ...        │         │   └─ Layer ...       │
    └─────────────────────┘         └─────────────────────┘

Key mapping details:

    OpenJD Step → OpenCue Layer
        Each step becomes a single layer. The step's name becomes the
        layer name (sanitised to alphanumeric + underscore + hyphen).

    OpenJD Task → OpenCue Frame
        Tasks are generated from a step's parameterSpace. The first INT
        parameter (usually "Frame") drives the OpenCue frame range.
        Steps with no parameterSpace become a single-frame layer (frame 1).

    OpenJD step dependencies → OpenCue layer dependencies
        "dependsOn" references are converted to PyOutline's depend_on()
        calls. Both forward and backward references are supported.

    OpenJD hostRequirements → OpenCue resource settings
        amount requirements (vcpu, memory) map to set_min_cores() and
        set_min_memory(). Attribute requirements (os.family, custom)
        map to OpenCue tags.

    OpenJD format strings → OpenCue tokens
        {{Param.X}}           → resolved to the parameter's value
        {{RawParam.X}}        → resolved to the parameter's value
        {{Task.Param.Frame}}  → replaced with #IFRAME# (OpenCue's
                                 per-frame substitution token)


What This Script Does NOT Handle (v1 Limitations)
--------------------------------------------------
    - OpenJD Environment lifecycle hooks (onEnter / onExit). These define
      setup/teardown scripts that run at session boundaries. OpenCue has
      no direct equivalent, so they are skipped for now.

    - OpenJD Environment Templates (external .env.yaml files). Only
      Job Templates are supported.

    - Complex multi-dimensional parameter spaces. If a step has multiple
      INT parameters, only the first one drives the frame range. If a step
      has only STRING parameters, a synthetic 1-N range is created from
      the combination count.

    - OpenJD path remapping. The specification supports cross-platform
      path mapping (e.g., Windows ↔ Linux mount points). This converter
      passes paths through as-is.

    - Embedded files. OpenJD allows inline script content via the
      "embeddedFiles" mechanism. Not yet supported here.


Requirements
------------
    Always required:
        pip install pyyaml

    Required only for live submission (not needed for --dry-run or --emit-code):
        pip install pycue pyoutline

    Environment variable for submission:
        export CUEBOT_HOSTS=your-cuebot-hostname


Three Output Modes
------------------
    1. --dry-run (recommended first step)
       Prints a human-readable summary of the job, layers, frame ranges,
       commands, dependencies, and resource settings. Nothing is submitted.
       Use this to verify your template converts correctly.

       Example:
           python openjd_to_opencue.py job.yaml --show myshow --shot sh010 --dry-run

    2. --emit-code
       Generates a standalone Python script that uses PyOutline directly.
       Useful if you want to inspect, modify, or commit the submission
       code rather than relying on this converter at runtime.

       Example:
           python openjd_to_opencue.py job.yaml --show myshow --shot sh010 --emit-code > submit.py

    3. Default (live submission)
       Parses the template, builds a PyOutline Outline object, and submits
       it to the OpenCue deployment specified by $CUEBOT_HOSTS. Requires
       pycue and pyoutline to be installed.

       Example:
           python openjd_to_opencue.py job.yaml --show myshow --shot sh010


CLI Usage
---------
    python openjd_to_opencue.py <template> --show <show> --shot <shot> [options]

    Positional arguments:
        template              Path to an OpenJD .yaml or .json job template

    Required:
        --show SHOW           OpenCue show name
        --shot SHOT           OpenCue shot name

    Optional:
        --user USER           OpenCue user (defaults to $USER)
        -p KEY=VALUE          Override a job parameter (repeatable)
        --min-cores N         Override min cores for all layers
        --max-cores N         Override max cores for all layers
        --min-memory N        Override min memory (MB) for all layers
        --dry-run             Print conversion summary, don't submit
        --emit-code           Print equivalent PyOutline Python script

    Examples:
        # Dry-run with default parameters
        python openjd_to_opencue.py hello.yaml --show test --shot sh01 --dry-run

        # Submit with parameter overrides
        python openjd_to_opencue.py render.yaml --show film --shot sh030 \\
            -p SceneFile=/scenes/sh030.blend -p FrameEnd=200

        # Generate PyOutline code for review
        python openjd_to_opencue.py pipeline.yaml --show film --shot sh030 \\
            --emit-code > submit_sh030.py


Minimal Template Example
-------------------------
    specificationVersion: jobtemplate-2023-09
    name: HelloWorld
    steps:
      - name: SayHello
        parameterSpace:
          taskParameterDefinitions:
            - name: Frame
              type: INT
              range: "1-10"
        script:
          actions:
            onRun:
              command: echo
              args:
                - "hello world - frame {{Task.Param.Frame}}"

    This creates an OpenCue job with one layer ("SayHello") and 10 frames.
    Each frame runs:  echo hello world - frame <N>


Architecture
------------
    The converter works in three phases:

    Phase 1: Parse & Validate
        load_template()      — reads YAML or JSON from disk
        validate_template()  — checks specificationVersion, step names,
                               dependency references

    Phase 2: Convert
        convert_template()   — orchestrates the full conversion:
            resolve_job_parameters()  — merges template defaults with
                                        CLI overrides (-p flags)
            extract_frame_info()      — reads parameterSpace, identifies
                                        the INT param driving frames,
                                        converts range syntax
            build_command()           — assembles the command + args list,
                                        substituting {{Param.X}} with
                                        resolved values and
                                        {{Task.Param.Frame}} with #IFRAME#
            extract_resources()       — maps hostRequirements to OpenCue
                                        cores, memory, and tags

        The output is a ConvertedJob containing ConvertedLayers — a clean
        intermediate representation that is independent of both OpenJD and
        OpenCue data structures.

    Phase 3: Output
        print_dry_run()        — human-readable summary to stdout
        emit_pyoutline_code()  — generates standalone Python script
        submit_to_opencue()    — builds PyOutline objects and submits


Author: Generated with Claude (Anthropic)
License: Apache-2.0
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# YAML import (required)
#
# PyYAML is the only hard dependency. It's needed even for --dry-run because
# most OpenJD templates are authored in YAML. JSON templates also work and
# are parsed with the stdlib json module.
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# OpenCue imports (optional)
#
# These are only needed when actually submitting to a live OpenCue deployment
# (i.e., when neither --dry-run nor --emit-code is used). This allows the
# script to be used for template validation and code generation on machines
# that don't have the OpenCue Python packages installed.
# ---------------------------------------------------------------------------
_HAS_OPENCUE = False
try:
    import outline
    import outline.cuerun
    import outline.modules.shell
    import opencue

    _HAS_OPENCUE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The only OpenJD specification version currently supported by this converter.
# The "jobtemplate-2023-09" version is the initial (and as of 2024, only)
# published version of the OpenJD specification.
SUPPORTED_SPEC_VERSIONS = {"jobtemplate-2023-09"}

# Regex for OpenJD format strings.
#
# OpenJD uses double-brace syntax for variable substitution in commands
# and arguments. There are three scopes:
#
#   {{Param.X}}         — Job-level parameter, resolved before submission.
#   {{RawParam.X}}      — Same as Param but bypasses path mapping. For this
#                          converter they behave identically since we don't
#                          implement path remapping.
#   {{Task.Param.X}}    — Task-level parameter, resolved per-frame at
#                          runtime. We convert the frame-driving one to
#                          OpenCue's #IFRAME# token.
#
# The regex captures the scope prefix (group 1) and parameter name (group 2).
_FORMAT_RE = re.compile(r"\{\{\s*(Task\.Param|Param|RawParam)\.(\w+)\s*\}\}")


# ===================================================================
# Phase 1: Template loading & validation
# ===================================================================


def load_template(path: str) -> dict:
    """
    Load an OpenJD template from a YAML or JSON file.

    Accepts .yaml, .yml, and .json extensions. For other extensions,
    tries YAML first (since YAML is a superset of JSON) then falls
    back to JSON.

    Args:
        path: Filesystem path to the template file.

    Returns:
        Parsed template as a Python dict.

    Raises:
        FileNotFoundError: If the template file doesn't exist.
        ValueError:        If the file doesn't parse to a dict.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Template not found: {path}")

    text = p.read_text(encoding="utf-8")

    if p.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif p.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        # Unknown extension — try YAML first (superset of JSON), then JSON
        try:
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("Template root must be a mapping/object")

    return data


def validate_template(template: dict) -> None:
    """
    Perform structural validation on a parsed OpenJD template.

    Checks performed:
        - specificationVersion is a supported value
        - Template has a 'name' field
        - At least one step is defined
        - All step names are unique
        - All dependency references point to existing step names

    This is intentionally lighter than the full validation provided by
    the openjd-model library. It catches the most common authoring
    mistakes without requiring that library as a dependency.

    Args:
        template: Parsed template dict from load_template().

    Raises:
        ValueError: If any validation check fails.
    """
    # --- Check specification version ---
    spec = template.get("specificationVersion", "")
    if spec not in SUPPORTED_SPEC_VERSIONS:
        raise ValueError(
            f"Unsupported specificationVersion '{spec}'. "
            f"Supported: {SUPPORTED_SPEC_VERSIONS}"
        )

    # --- Check job name ---
    if "name" not in template:
        raise ValueError("Template must have a 'name' field")

    # --- Check steps exist ---
    steps = template.get("steps")
    if not steps or not isinstance(steps, list):
        raise ValueError("Template must have at least one step")

    # --- Check step names are unique and dependencies are valid ---
    # First pass: collect all step names
    step_names = set()
    for i, step in enumerate(steps):
        name = step.get("name")
        if not name:
            raise ValueError(f"Step {i} is missing a 'name'")
        if name in step_names:
            raise ValueError(f"Duplicate step name: '{name}'")
        step_names.add(name)

        # Note: we don't validate dependencies here because a step might
        # reference a step defined later in the list. We do a second pass
        # below after all names are collected.

    # Second pass: validate all dependency references
    for step in steps:
        for dep in step.get("dependencies", []):
            dep_name = dep.get("dependsOn", "")
            if dep_name not in step_names:
                raise ValueError(
                    f"Step '{step['name']}' depends on unknown step '{dep_name}'"
                )


# ===================================================================
# Phase 2a: Parameter resolution
# ===================================================================


def resolve_job_parameters(
    template: dict, overrides: dict[str, str]
) -> dict[str, str]:
    """
    Build a complete job parameter dict from template defaults + CLI overrides.

    OpenJD templates can define parameterDefinitions at the job level.
    Each parameter has a name, type (STRING, INT, FLOAT, PATH), and
    optionally a default value. At submission time, every parameter must
    have a resolved value — either from its default or from a CLI override.

    Override priority:
        CLI -p flag  >  template default

    Args:
        template:  Parsed OpenJD template dict.
        overrides: Dict of {param_name: value_string} from CLI -p flags.

    Returns:
        Dict of {param_name: resolved_value_string} for all declared params.

    Raises:
        ValueError: If a parameter has no default and wasn't provided via -p.
    """
    params: dict[str, str] = {}

    for pdef in template.get("parameterDefinitions", []):
        name = pdef["name"]
        ptype = pdef.get("type", "STRING")

        if name in overrides:
            # CLI override takes precedence
            params[name] = overrides[name]
        elif "default" in pdef:
            # Fall back to template default
            params[name] = str(pdef["default"])
        else:
            # No value available — can't proceed
            raise ValueError(
                f"Job parameter '{name}' ({ptype}) has no default and was not "
                f"provided via --param / -p"
            )

    return params


# ===================================================================
# Phase 2b: Parameter space → frame range conversion
# ===================================================================


def _expand_int_range(range_str: str) -> list[int]:
    """
    Expand an OpenJD INT range string into a list of integers.

    Supports multiple formats:
        "1-100"       → [1, 2, 3, ..., 100]
        "1-100:5"     → [1, 6, 11, ..., 96]   (step of 5)
        "1,2,5,10"    → [1, 2, 5, 10]
        "1-10,20-30"  → [1, 2, ..., 10, 20, 21, ..., 30]

    Note: This function is available for future use (e.g., counting tasks
    or validating ranges) but is not directly used in the current conversion
    pipeline because OpenCue accepts range strings natively.

    Args:
        range_str: An OpenJD-format integer range string.

    Returns:
        List of integers in the range.
    """
    values: list[int] = []
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            # Could have a step suffix: "1-100:5"
            if ":" in part:
                rng, step_str = part.rsplit(":", 1)
                step = int(step_str)
            else:
                rng = part
                step = 1
            start_s, end_s = rng.split("-", 1)
            start, end = int(start_s), int(end_s)
            values.extend(range(start, end + 1, step))
        else:
            values.append(int(part))
    return values


def extract_frame_info(step: dict, job_params: dict[str, str]) -> dict:
    """
    Extract frame range information from a step's parameterSpace.

    This is the core of the OpenJD-to-OpenCue task mapping. OpenJD defines
    tasks via a parameterSpace with one or more taskParameterDefinitions.
    OpenCue defines frames via a simple range string (e.g., "1-100").

    The mapping strategy:
        1. If no parameterSpace → single frame (range "1-1")
        2. If there are INT parameters → the first one drives the frame range
        3. If there are only STRING parameters → count combinations, create
           a synthetic 1-N range (lossy but functional for v1)

    Frame range syntax conversion:
        OpenJD uses ":" for step:   "1-100:5"
        OpenCue uses "x" for step:  "1-100x5"

    Args:
        step:       A single step dict from the template.
        job_params: Resolved job parameters (needed because range strings
                    can contain {{Param.X}} references).

    Returns:
        Dict with keys:
            frame_range:  str — OpenCue-format range (e.g., "1-100", "1-100x5")
            frame_param:  str or None — name of the INT param used as frame index
            chunk:        int — number of frames to process per task (default 1)
            extra_params: dict — any non-frame task parameters (for reference)
    """
    ps = step.get("parameterSpace")
    if not ps:
        # No parameter space defined → this step runs as a single task.
        # We represent this as frame 1 in OpenCue.
        return {
            "frame_range": "1-1",
            "frame_param": None,
            "chunk": 1,
            "extra_params": {},
        }

    task_params = ps.get("taskParameterDefinitions", [])
    if not task_params:
        return {
            "frame_range": "1-1",
            "frame_param": None,
            "chunk": 1,
            "extra_params": {},
        }

    # Separate INT parameters (frame candidates) from others
    int_params = [p for p in task_params if p.get("type", "INT") == "INT"]
    other_params = [p for p in task_params if p.get("type", "INT") != "INT"]

    if not int_params:
        # No INT parameters — all STRING. This is a more complex case where
        # OpenJD generates task combinations from string value lists.
        # OpenCue doesn't have a native equivalent, so we create a synthetic
        # frame range of 1-N where N = total number of combinations.
        # The actual parameter values would need to be resolved at runtime
        # by a wrapper script (not implemented in v1).
        combo_count = 1
        extra = {}
        for p in task_params:
            vals = p.get("range", p.get("values", []))
            if isinstance(vals, list):
                combo_count *= max(len(vals), 1)
                extra[p["name"]] = vals
            elif isinstance(vals, str):
                expanded = [v.strip() for v in vals.split(",")]
                combo_count *= len(expanded)
                extra[p["name"]] = expanded
        return {
            "frame_range": f"1-{combo_count}",
            "frame_param": None,
            "chunk": 1,
            "extra_params": extra,
        }

    # Use the first INT parameter as the frame-driving parameter.
    # In most VFX templates this is named "Frame" — but OpenJD allows
    # any name, so we handle it generically.
    primary = int_params[0]
    range_str = str(primary.get("range", "1-1"))

    # The range string itself can contain job parameter references
    # (e.g., "{{Param.FrameStart}}-{{Param.FrameEnd}}"), so we need
    # to resolve those before passing to OpenCue.
    range_str = _substitute_job_params(range_str, job_params)

    # Convert OpenJD step syntax to OpenCue step syntax:
    #   OpenJD:  "1-100:5"  (colon = step)
    #   OpenCue: "1-100x5"  (x = step)
    opencue_range = range_str.replace(":", "x")

    return {
        "frame_range": opencue_range,
        "frame_param": primary["name"],
        "chunk": int(ps.get("chunkSize", primary.get("chunkSize", 1))),
        "extra_params": {
            p["name"]: p.get("range", p.get("values", "")) for p in other_params
        },
    }


# ===================================================================
# Phase 2c: Format string substitution
# ===================================================================


def _substitute_job_params(text: str, job_params: dict[str, str]) -> str:
    """
    Replace job-level format strings with their resolved values.

    Handles two scopes:
        {{Param.X}}     → replaced with the resolved value of parameter X
        {{RawParam.X}}  → same (we don't implement path remapping)

    Leaves task-level references ({{Task.Param.X}}) untouched — those are
    handled separately in build_command() where they become #IFRAME#.

    Args:
        text:       Any string that may contain {{...}} format references.
        job_params: Resolved job parameters from resolve_job_parameters().

    Returns:
        String with Param/RawParam references replaced. Unrecognised
        parameter names are left as-is (the original {{...}} text).
    """

    def _replace(m):
        scope = m.group(1)  # "Param", "RawParam", or "Task.Param"
        name = m.group(2)  # parameter name
        if scope in ("Param", "RawParam"):
            return job_params.get(name, m.group(0))
        return m.group(0)  # leave Task.Param references alone

    return _FORMAT_RE.sub(_replace, text)


def build_command(
    step: dict, job_params: dict[str, str], frame_param: str | None
) -> list[str]:
    """
    Build the shell command list for a step, performing all substitutions.

    OpenJD defines commands in a structured way:
        script:
          actions:
            onRun:
              command: "executable"
              args: ["arg1", "arg2", ...]

    This function:
        1. Extracts the command and args into a flat list
        2. Replaces {{Param.X}} / {{RawParam.X}} with resolved values
        3. Replaces {{Task.Param.<frame_param>}} with #IFRAME# — this is
           OpenCue's per-frame substitution token that RQD replaces with
           the actual frame number at execution time

    Args:
        step:        A single step dict from the template.
        job_params:  Resolved job parameters.
        frame_param: Name of the INT parameter driving frames (e.g., "Frame"),
                     or None if the step has no parameterSpace.

    Returns:
        List of strings forming the complete command (e.g.,
        ["echo", "hello world - frame #IFRAME#"]).
    """
    # Navigate into the step's script structure.
    # OpenJD allows onRun, onEnter, and onExit actions — we only use onRun
    # since that's what actually runs the work. onEnter/onExit are
    # environment lifecycle hooks which we skip in this version.
    script = step.get("script", {})
    actions = script.get("actions", {})
    on_run = actions.get("onRun", {})

    command_str = on_run.get("command", "")
    args = on_run.get("args", [])

    # Build a flat command list: [command, arg1, arg2, ...]
    parts = [command_str] + [str(a) for a in args]

    resolved: list[str] = []
    for part in parts:
        # Step 1: Replace job-level parameters ({{Param.X}}, {{RawParam.X}})
        part = _substitute_job_params(part, job_params)

        # Step 2: Replace the task frame parameter with OpenCue's #IFRAME# token.
        # We handle both the exact-match format and a more relaxed regex
        # to be tolerant of whitespace inside the braces.
        if frame_param:
            # Exact match (no extra whitespace)
            part = part.replace(
                "{{{{Task.Param.{fp}}}}}".format(fp=frame_param), "#IFRAME#"
            )
            # Relaxed match (allows whitespace: {{ Task.Param.Frame }})
            part = re.sub(
                r"\{\{\s*Task\.Param\." + re.escape(frame_param) + r"\s*\}\}",
                "#IFRAME#",
                part,
            )

        resolved.append(part)

    return resolved


# ===================================================================
# Phase 2d: Host requirements → OpenCue resource settings
# ===================================================================


def extract_resources(step: dict) -> dict:
    """
    Map OpenJD hostRequirements to OpenCue resource settings.

    OpenJD defines two types of host requirements:

        amounts: Numeric quantities the host must provide.
            Example: {"name": "amount.worker.vcpu", "min": 4}
            These map to OpenCue's set_min_cores() / set_min_memory().

        attributes: Named properties the host must have.
            Example: {"name": "attr.worker.os.family", "anyOf": ["linux"]}
            These map to OpenCue tags, which can be used with OpenCue's
            tagging system to route jobs to specific machine types.

    The mapping is based on keyword matching in the requirement names:
        "vcpu", "cpu", "core"  → min_cores / max_cores
        "memory", "ram"        → min_memory (in MB)
        Everything else        → tags

    Args:
        step: A single step dict from the template.

    Returns:
        Dict with keys:
            min_cores:  int or None
            max_cores:  int or None
            min_memory: int or None (megabytes)
            service:    str or None (not yet used, placeholder for future)
            tags:       list[str]
    """
    result = {
        "min_cores": None,
        "max_cores": None,
        "min_memory": None,
        "service": None,
        "tags": [],
    }

    hr = step.get("hostRequirements")
    if not hr:
        return result

    # --- Amount requirements (numeric) ---
    for amt in hr.get("amounts", []):
        name = amt.get("name", "")
        min_val = amt.get("min")
        max_val = amt.get("max")

        if "vcpu" in name or "cpu" in name or "core" in name:
            if min_val is not None:
                result["min_cores"] = int(min_val)
            if max_val is not None:
                result["max_cores"] = int(max_val)
        elif "memory" in name or "ram" in name:
            # Both OpenJD and OpenCue use megabytes as the unit
            if min_val is not None:
                result["min_memory"] = int(min_val)

    # --- Attribute requirements (categorical) ---
    # These become OpenCue tags. In OpenCue, tags are used to match jobs
    # to hosts — e.g., a host tagged "linux" will only run layers that
    # are also tagged "linux" (or have no tag restriction).
    for attr in hr.get("attributes", []):
        any_of = attr.get("anyOf", [])
        all_of = attr.get("allOf", [])
        result["tags"].extend(any_of or all_of)

    return result


# ===================================================================
# Phase 2e: Intermediate representation
# ===================================================================


class ConvertedLayer:
    """
    Intermediate representation of an OpenCue layer (converted from an OpenJD step).

    This is a plain data class that holds everything needed to create a
    PyOutline Shell layer, without depending on either OpenJD or OpenCue
    libraries. This makes it easy to serialise (dry-run, emit-code) or
    submit (PyOutline).

    Attributes:
        name:        Layer name (sanitised for OpenCue: alphanumeric, _, -)
        command:     Full command as a list of strings, with all parameter
                     substitutions applied and frame tokens in place
        frame_range: OpenCue-format frame range string (e.g., "1-100", "1-100x5")
        chunk:       Number of frames per task (1 = one frame per task)
        depends_on:  List of layer names this layer depends on
        min_cores:   Minimum CPU cores required, or None
        max_cores:   Maximum CPU cores to use, or None
        min_memory:  Minimum memory in MB, or None
        service:     OpenCue service type (future use), or None
        tags:        List of OpenCue tag strings for host matching
        env_vars:    Dict of environment variables to set for this layer
    """

    def __init__(self):
        self.name: str = ""
        self.command: list[str] = []
        self.frame_range: str = "1-1"
        self.chunk: int = 1
        self.depends_on: list[str] = []
        self.min_cores: int | None = None
        self.max_cores: int | None = None
        self.min_memory: int | None = None
        self.service: str | None = None
        self.tags: list[str] = []
        self.env_vars: dict[str, str] = {}

    def __repr__(self):
        return f"<Layer '{self.name}' range={self.frame_range} cmd={self.command}>"


class ConvertedJob:
    """
    Intermediate representation of an OpenCue job (converted from an OpenJD template).

    Contains all the metadata and layers needed to either print a summary,
    generate PyOutline code, or submit directly to OpenCue.

    Attributes:
        name:   Job name (sanitised for OpenCue)
        show:   OpenCue show name (provided via CLI --show)
        shot:   OpenCue shot name (provided via CLI --shot)
        user:   Submitting user (provided via CLI --user or $USER)
        layers: List of ConvertedLayer objects in submission order
    """

    def __init__(self):
        self.name: str = ""
        self.show: str = ""
        self.shot: str = ""
        self.user: str = ""
        self.layers: list[ConvertedLayer] = []

    def __repr__(self):
        return f"<Job '{self.name}' show={self.show} layers={len(self.layers)}>"


# ===================================================================
# Phase 2f: Main conversion orchestrator
# ===================================================================


def convert_template(
    template: dict,
    show: str,
    shot: str,
    user: str,
    param_overrides: dict[str, str],
    resource_overrides: dict | None = None,
) -> ConvertedJob:
    """
    Convert a validated OpenJD template into a ConvertedJob.

    This is the main entry point for the conversion pipeline. It:
        1. Resolves all job-level parameters
        2. Iterates over each step and builds a ConvertedLayer
        3. For each step: extracts frame range, builds command, maps
           dependencies, and extracts resource requirements
        4. Applies any CLI resource overrides on top

    Args:
        template:           Parsed and validated OpenJD template dict.
        show:               OpenCue show name.
        shot:               OpenCue shot name.
        user:               Submitting user name.
        param_overrides:    Dict of CLI parameter overrides from -p flags.
        resource_overrides: Optional dict with keys "min_cores", "max_cores",
                            "min_memory" to override all layers uniformly.

    Returns:
        A fully populated ConvertedJob ready for output.
    """
    resource_overrides = resource_overrides or {}

    # --- Resolve job-level parameters ---
    job_params = resolve_job_parameters(template, param_overrides)

    # --- Build the job name ---
    # The template name can contain parameter references (e.g.,
    # "Render_{{Param.ShotName}}"), so we substitute those first,
    # then sanitise for OpenCue (only alphanumeric, underscore, hyphen, dot).
    job_name_raw = template["name"]
    job_name = _substitute_job_params(job_name_raw, job_params)
    job_name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", job_name)

    job = ConvertedJob()
    job.name = job_name
    job.show = show
    job.shot = shot
    job.user = user

    # --- Convert each step to a layer ---
    for step in template.get("steps", []):
        layer = ConvertedLayer()

        # Sanitise the step name for use as an OpenCue layer name
        layer.name = re.sub(r"[^a-zA-Z0-9_\-]", "_", step["name"])

        # Extract frame range from the step's parameterSpace
        frame_info = extract_frame_info(step, job_params)
        layer.frame_range = frame_info["frame_range"]
        layer.chunk = frame_info["chunk"]

        # Build the command with all substitutions applied
        layer.command = build_command(step, job_params, frame_info["frame_param"])

        # Map step dependencies to layer dependencies
        for dep in step.get("dependencies", []):
            dep_name = dep.get("dependsOn", "")
            layer.depends_on.append(re.sub(r"[^a-zA-Z0-9_\-]", "_", dep_name))

        # Extract resource requirements from hostRequirements
        resources = extract_resources(step)

        # CLI resource overrides take precedence over template values
        layer.min_cores = resource_overrides.get("min_cores") or resources["min_cores"]
        layer.max_cores = resource_overrides.get("max_cores") or resources["max_cores"]
        layer.min_memory = (
            resource_overrides.get("min_memory") or resources["min_memory"]
        )
        layer.service = resources["service"]
        layer.tags = resources["tags"]

        # Extract any step-level environment variables.
        # Note: these come from script.variables (simple key-value pairs),
        # NOT from stepEnvironments (which have onEnter/onExit lifecycle
        # hooks that we skip in v1).
        script_vars = step.get("script", {}).get("variables", {})
        for k, v in script_vars.items():
            layer.env_vars[k] = _substitute_job_params(str(v), job_params)

        job.layers.append(layer)

    return job


# ===================================================================
# Phase 3a: Output — dry-run summary
# ===================================================================


def print_dry_run(job: ConvertedJob) -> None:
    """
    Print a human-readable summary of the converted job.

    This is the recommended first step when working with a new template.
    It shows exactly what would be submitted to OpenCue without actually
    submitting anything — the job name, all layers, their frame ranges,
    commands, dependencies, and resource settings.

    Args:
        job: A ConvertedJob from convert_template().
    """
    print("=" * 70)
    print(f"  DRY RUN — OpenJD → OpenCue Conversion")
    print("=" * 70)
    print(f"  Job Name : {job.name}")
    print(f"  Show     : {job.show}")
    print(f"  Shot     : {job.shot}")
    print(f"  User     : {job.user}")
    print(f"  Layers   : {len(job.layers)}")
    print("=" * 70)

    for i, layer in enumerate(job.layers, 1):
        print(f"\n  Layer {i}: {layer.name}")
        print(f"  {'─' * 40}")
        print(f"    Frame range : {layer.frame_range}")
        print(f"    Chunk size  : {layer.chunk}")
        print(f"    Command     : {' '.join(layer.command)}")

        if layer.depends_on:
            print(f"    Depends on  : {', '.join(layer.depends_on)}")

        if layer.min_cores:
            print(f"    Min cores   : {layer.min_cores}")
        if layer.max_cores:
            print(f"    Max cores   : {layer.max_cores}")
        if layer.min_memory:
            print(f"    Min memory  : {layer.min_memory} MB")
        if layer.tags:
            print(f"    Tags        : {', '.join(layer.tags)}")
        if layer.env_vars:
            print(f"    Env vars    :")
            for k, v in layer.env_vars.items():
                print(f"      {k}={v}")

    print(f"\n{'=' * 70}")
    print("  To submit for real, remove the --dry-run flag.")
    print("=" * 70)


# ===================================================================
# Phase 3b: Output — emit equivalent PyOutline code
# ===================================================================


def emit_pyoutline_code(job: ConvertedJob) -> str:
    """
    Generate a standalone PyOutline Python script from the converted job.

    The generated script can be:
        - Inspected to understand exactly what PyOutline calls will be made
        - Modified for special cases the converter doesn't handle
        - Committed to version control as a reproducible submission script
        - Run directly: python submit.py

    The generated code uses outline.Outline and outline.modules.shell.Shell,
    which are the standard PyOutline classes for job and layer construction.

    Args:
        job: A ConvertedJob from convert_template().

    Returns:
        Complete Python script as a string.
    """
    lines: list[str] = []
    lines.append("#!/usr/bin/env python3")
    lines.append('"""Auto-generated PyOutline submission from OpenJD template."""')
    lines.append("")
    lines.append("import outline")
    lines.append("import outline.modules.shell")
    lines.append("")
    lines.append("")
    lines.append("def main():")
    lines.append(f"    # Create job")
    lines.append(f"    job = outline.Outline(")
    lines.append(f'        name="{job.name}",')
    lines.append(f'        shot="{job.shot}",')
    lines.append(f'        show="{job.show}",')
    lines.append(f'        user="{job.user}",')
    lines.append(f"    )")
    lines.append("")

    # Generate a variable for each layer so we can reference them
    # when wiring up dependencies
    layer_vars: dict[str, str] = {}
    for i, layer in enumerate(job.layers):
        var = f"layer_{layer.name.lower()}"
        layer_vars[layer.name] = var

        cmd_repr = repr(layer.command)
        lines.append(f"    # Layer: {layer.name}")
        lines.append(f"    {var} = outline.modules.shell.Shell(")
        lines.append(f'        name="{layer.name}",')
        lines.append(f"        command={cmd_repr},")
        lines.append(f'        range="{layer.frame_range}",')
        if layer.chunk > 1:
            lines.append(f"        chunk={layer.chunk},")
        lines.append(f"    )")

        if layer.min_cores:
            lines.append(f"    {var}.set_min_cores({layer.min_cores})")
        if layer.max_cores:
            lines.append(f"    {var}.set_max_cores({layer.max_cores})")
        if layer.min_memory:
            lines.append(f"    {var}.set_min_memory({layer.min_memory})")

        for k, v in layer.env_vars.items():
            lines.append(f'    {var}.set_env("{k}", "{v}")')

        lines.append("")

    # Wire up dependencies between layers
    for layer in job.layers:
        var = layer_vars[layer.name]
        for dep_name in layer.depends_on:
            dep_var = layer_vars.get(dep_name, f"layer_{dep_name.lower()}")
            lines.append(f"    {var}.depend_on({dep_var})")

    if any(l.depends_on for l in job.layers):
        lines.append("")

    # Add all layers to the job
    for layer in job.layers:
        var = layer_vars[layer.name]
        lines.append(f"    job.add_layer({var})")

    lines.append("")
    lines.append("    # Submit via OutlineLauncher (use_pycuerun=False runs commands directly)")
    lines.append("    import outline.cuerun")
    lines.append("    launcher = outline.cuerun.OutlineLauncher(job)")
    lines.append(f'    launcher.set_flag("show", "{job.show}")')
    lines.append(f'    launcher.set_flag("shot", "{job.shot}")')
    lines.append(f'    launcher.set_flag("user", "{job.user}")')
    lines.append("    launcher.launch(use_pycuerun=False)")
    lines.append('    print(f"Submitted job: {job.name}")')
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    main()")
    lines.append("")

    return "\n".join(lines)


# ===================================================================
# Phase 3c: Output — live submission to OpenCue
# ===================================================================


def submit_to_opencue(job: ConvertedJob) -> None:
    """
    Submit the converted job to a live OpenCue deployment via PyOutline.

    This builds real PyOutline objects (Outline, Shell layers) and calls
    setup() + launch() to submit to the Cuebot server. Requires:
        - pycue and pyoutline packages installed
        - CUEBOT_HOSTS environment variable set to the Cuebot hostname

    The submission flow:
        1. Create an Outline (job container)
        2. Create Shell layers for each ConvertedLayer
        3. Set resource requirements on each layer
        4. Wire up dependencies between layers
        5. Add all layers to the job
        6. Call setup() then launch() to submit

    Args:
        job: A ConvertedJob from convert_template().

    Raises:
        SystemExit: If OpenCue libraries are not installed.
    """
    if not _HAS_OPENCUE:
        print(
            "ERROR: OpenCue libraries not found.\n"
            "Install with: pip install pycue pyoutline\n"
            "And set CUEBOT_HOSTS environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    cuebot = os.environ.get("CUEBOT_HOSTS")
    if not cuebot:
        print(
            "WARNING: CUEBOT_HOSTS not set. Defaulting to 'localhost'.\n"
            "Set it with: export CUEBOT_HOSTS=your-cuebot-hostname",
            file=sys.stderr,
        )

    # --- Build the PyOutline job ---
    ol = outline.Outline(
        name=job.name,
        shot=job.shot,
        show=job.show,
        user=job.user,
    )

    # Keep references to created layers so we can wire up dependencies
    layer_objects: dict[str, Any] = {}

    for layer in job.layers:
        shell = outline.modules.shell.Shell(
            name=layer.name,
            command=layer.command,
            range=layer.frame_range,
            chunk=layer.chunk,
        )

        # Set resource requirements
        if layer.min_cores:
            shell.set_min_cores(layer.min_cores)
        if layer.max_cores:
            shell.set_max_cores(layer.max_cores)
        if layer.min_memory:
            shell.set_min_memory(layer.min_memory)

        # Set environment variables
        for k, v in layer.env_vars.items():
            shell.set_env(k, v)

        layer_objects[layer.name] = shell

    # Wire up inter-layer dependencies
    for layer in job.layers:
        shell = layer_objects[layer.name]
        for dep_name in layer.depends_on:
            dep_shell = layer_objects.get(dep_name)
            if dep_shell:
                shell.depend_on(dep_shell)

    # Add all layers to the job in order
    for layer in job.layers:
        ol.add_layer(layer_objects[layer.name])

    # Submit to OpenCue via OutlineLauncher.
    #
    # PyOutline doesn't expose a simple job.launch() method. Instead it
    # uses a launcher/backend system:
    #   1. OutlineLauncher wraps the Outline and holds submission settings
    #   2. launcher.set_flag() configures show/shot/user/facility
    #   3. launcher.launch() serialises the job to XML and calls
    #      opencue.api.launchSpecAndWait() on the backend
    #
    # We use use_pycuerun=False so commands run directly on the render
    # host rather than being wrapped in pycuerun (which would require
    # the Outline file to exist on a shared filesystem).
    launcher = outline.cuerun.OutlineLauncher(ol)
    launcher.set_flag("show", job.show)
    launcher.set_flag("shot", job.shot)
    launcher.set_flag("user", job.user)

    # --- Debug: print the XML spec that will be sent to Cuebot ---
    try:
        xml_spec = launcher.serialize(use_pycuerun=False)
        print("\n[DEBUG] Cuebot host(s):", os.environ.get("CUEBOT_HOSTS", "(not set)"))
        print("\n[DEBUG] Serialised job spec XML:")
        print("-" * 60)

        # Pretty-print the XML for readability
        from xml.dom.minidom import parseString
        try:
            pretty = parseString(xml_spec).toprettyxml(indent="  ")
            print(pretty)
        except Exception:
            # If pretty-print fails, dump raw
            print(xml_spec)

        print("-" * 60)
    except Exception as e:
        print(f"\n[DEBUG] ERROR during serialisation: {type(e).__name__}: {e}",
              file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # --- Submit ---
    try:
        jobs = launcher.launch(use_pycuerun=False)

        # Inspect what came back
        if jobs:
            print(f"\n[DEBUG] launch() returned {len(jobs)} job(s):")
            for j in jobs:
                try:
                    print(f"  - Name: {j.name()}")
                    print(f"    ID:   {j.id()}")
                    print(f"    State: {j.state()}")
                except Exception:
                    print(f"  - Job object: {j}")
        else:
            print("\n[DEBUG] WARNING: launch() returned empty/None — "
                  "job may not have been submitted.", file=sys.stderr)

        print(f"\nSubmitted job '{job.name}' to OpenCue ({len(job.layers)} layers)")

    except Exception as e:
        print(f"\n[DEBUG] ERROR during submission: {type(e).__name__}: {e}",
              file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ===================================================================
# CLI: argument parsing and entry point
# ===================================================================


def parse_param_arg(param_str: str) -> tuple[str, str]:
    """
    Parse a CLI parameter override string in "Key=Value" format.

    Used with the -p / --param flag to override job parameters defined
    in the template. For example: -p SceneFile=/scenes/shot.blend

    Args:
        param_str: A string in "Key=Value" format.

    Returns:
        Tuple of (key, value) strings.

    Raises:
        argparse.ArgumentTypeError: If the string doesn't contain "=".
    """
    if "=" not in param_str:
        raise argparse.ArgumentTypeError(
            f"Parameter must be in Key=Value format, got: '{param_str}'"
        )
    key, _, value = param_str.partition("=")
    return key.strip(), value.strip()


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argparse parser for the CLI.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="openjd_to_opencue",
        description="Convert Open Job Description templates to OpenCue jobs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s job.yaml --show myshow --shot sh010 --dry-run
  %(prog)s job.yaml --show myshow --shot sh010
  %(prog)s job.yaml --show myshow --shot sh010 -p SceneFile=shot.blend
  %(prog)s job.yaml --show myshow --shot sh010 --emit-code > submit.py
        """,
    )

    parser.add_argument(
        "template",
        help="Path to an OpenJD job template file (.yaml or .json)",
    )

    # --- Required OpenCue metadata ---
    # These are required because OpenCue's job model always needs a show
    # and shot to organise work. They don't exist in the OpenJD template
    # because OpenJD is scheduler-agnostic.
    parser.add_argument(
        "--show",
        required=True,
        help="OpenCue show name (e.g. 'myshow')",
    )
    parser.add_argument(
        "--shot",
        required=True,
        help="OpenCue shot name (e.g. 'sh010')",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="OpenCue user (default: current OS user from $USER)",
    )

    # --- Job parameter overrides ---
    parser.add_argument(
        "-p",
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Override a job parameter defined in the template. "
            "Can be repeated for multiple parameters. "
            "Example: -p FrameEnd=200 -p SceneFile=/path/to/scene.blend"
        ),
    )

    # --- Resource overrides ---
    # These apply uniformly to ALL layers and take precedence over
    # anything defined in the template's hostRequirements.
    parser.add_argument(
        "--min-cores",
        type=int,
        default=None,
        help="Override minimum cores for all layers",
    )
    parser.add_argument(
        "--max-cores",
        type=int,
        default=None,
        help="Override maximum cores for all layers",
    )
    parser.add_argument(
        "--min-memory",
        type=int,
        default=None,
        help="Override minimum memory (MB) for all layers",
    )

    # --- Output mode ---
    # Mutually exclusive: you can dry-run, emit code, or submit (default).
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be submitted without actually submitting",
    )
    mode.add_argument(
        "--emit-code",
        action="store_true",
        help="Output equivalent PyOutline Python code to stdout",
    )

    return parser


def main() -> None:
    """
    CLI entry point.

    Workflow:
        1. Parse CLI arguments
        2. Load and validate the template
        3. Resolve parameter overrides
        4. Convert to intermediate representation
        5. Output (dry-run, emit-code, or submit)
    """
    parser = build_parser()
    args = parser.parse_args()

    # --- Phase 1: Load and validate ---
    template = load_template(args.template)
    validate_template(template)

    # --- Parse CLI parameter overrides ---
    param_overrides: dict[str, str] = {}
    for p in args.param:
        key, value = parse_param_arg(p)
        param_overrides[key] = value

    # --- Determine submitting user ---
    user = args.user or os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

    # --- Collect resource overrides ---
    resource_overrides = {}
    if args.min_cores:
        resource_overrides["min_cores"] = args.min_cores
    if args.max_cores:
        resource_overrides["max_cores"] = args.max_cores
    if args.min_memory:
        resource_overrides["min_memory"] = args.min_memory

    # --- Phase 2: Convert ---
    job = convert_template(
        template=template,
        show=args.show,
        shot=args.shot,
        user=user,
        param_overrides=param_overrides,
        resource_overrides=resource_overrides,
    )

    # --- Phase 3: Output ---
    if args.dry_run:
        print_dry_run(job)
    elif args.emit_code:
        print(emit_pyoutline_code(job))
    else:
        submit_to_opencue(job)


if __name__ == "__main__":
    main()
