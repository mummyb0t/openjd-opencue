[README.md](https://github.com/user-attachments/files/26225119/README.md)
# openjd-to-opencue

A command-line converter that takes [Open Job Description](https://github.com/OpenJobDescription/openjd-specifications) (OpenJD) templates and submits them as jobs to [OpenCue](https://github.com/AcademySoftwareFoundation/OpenCue).

Write your jobs once in OpenJD's portable YAML format. This tool translates them into OpenCue's native structure and submits via PyOutline.

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [Quickstart (5 minutes)](#quickstart-5-minutes)
- [Installation](#installation)
- [CLI Reference](#cli-reference)
- [Template Authoring Guide](#template-authoring-guide)
  - [Minimal Template](#minimal-template)
  - [Job Name](#job-name)
  - [Parameters](#parameters)
  - [Steps](#steps)
  - [Frame Ranges (parameterSpace)](#frame-ranges-parameterspace)
  - [Commands (script)](#commands-script)
  - [Dependencies](#dependencies)
  - [Resource Requirements (hostRequirements)](#resource-requirements-hostrequirements)
  - [Environment Variables](#environment-variables)
- [Format Strings Reference](#format-strings-reference)
- [How the Concept Mapping Works](#how-the-concept-mapping-works)
- [Worked Examples](#worked-examples)
  - [Example 1: Hello World](#example-1-hello-world)
  - [Example 2: FFmpeg Transcode with Dependencies](#example-2-ffmpeg-transcode-with-dependencies)
  - [Example 3: Multi-Step VFX Pipeline](#example-3-multi-step-vfx-pipeline)
- [Output Modes](#output-modes)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [Limitations & Roadmap](#limitations--roadmap)
- [Upstream Projects](#upstream-projects)
- [License](#license)

---

## Why This Exists

OpenCue and OpenJD are both open-source, both aimed at VFX/animation render farms, and both live under the ASWF/AWS ecosystem — but no integration between them exists.

**OpenCue** is great at dispatching and managing work, but its job authoring is tightly coupled: you either use the CueSubmit GUI, write PyOutline Python scripts, or craft XML by hand. There's no portable, declarative template format.

**OpenJD** is great at describing work in a scheduler-agnostic way, but it's just a specification — it doesn't submit to anything on its own. The only existing runtime integration is with AWS Deadline.

This converter fills the gap. You get OpenJD's portable templates as your authoring layer, and OpenCue's battle-tested dispatch as your execution layer.

---

## Quickstart (5 minutes)

**1. Install the dependency:**

```bash
pip install pyyaml
```

**2. Create a template** (or use the included `examples/hello_world.yaml`):

```yaml
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
```

**3. Dry-run to see what would be submitted:**

```bash
python openjd_to_opencue.py hello_world.yaml --show testshow --shot test01 --dry-run
```

Output:

```
======================================================================
  DRY RUN — OpenJD → OpenCue Conversion
======================================================================
  Job Name : HelloWorld
  Show     : testshow
  Shot     : test01
  User     : yourname
  Layers   : 1
======================================================================

  Layer 1: SayHello
  ────────────────────────────────────────
    Frame range : 1-10
    Chunk size  : 1
    Command     : echo hello world - frame #IFRAME#

======================================================================
  To submit for real, remove the --dry-run flag.
======================================================================
```

**4. Submit for real** (requires OpenCue Python libs + a running Cuebot):

```bash
export CUEBOT_HOSTS=your-cuebot-hostname
pip install pycue pyoutline
python openjd_to_opencue.py hello_world.yaml --show testshow --shot test01
```

---

## Installation

### Required (always)

```bash
pip install pyyaml
```

### Required for live submission only

```bash
pip install pycue pyoutline
```

These are the OpenCue Python client libraries. You do **not** need them for `--dry-run` or `--emit-code` — the script gracefully degrades without them.

### Environment

```bash
# Tell the script where your Cuebot server lives
export CUEBOT_HOSTS=cuebot.yourstudio.com

# Optional: override the submitting user (defaults to $USER)
export USER=artist_name
```

### Python version

Python 3.10+ (uses `X | None` type union syntax). If you're on 3.9, replace `X | None` with `Optional[X]` from `typing`.

---

## CLI Reference

```
python openjd_to_opencue.py <template> --show <show> --shot <shot> [options]
```

### Positional argument

| Argument   | Description                                      |
|------------|--------------------------------------------------|
| `template` | Path to an OpenJD `.yaml` or `.json` template file |

### Required flags

| Flag          | Description                                        |
|---------------|----------------------------------------------------|
| `--show SHOW` | OpenCue show name (e.g., `myshow`, `feature_film`) |
| `--shot SHOT` | OpenCue shot name (e.g., `sh010`, `spot_01`)       |

These are required because OpenCue organises all work under a show/shot hierarchy. OpenJD doesn't have this concept (it's scheduler-agnostic), so you provide them at submission time.

### Optional flags

| Flag                  | Description                                                       |
|-----------------------|-------------------------------------------------------------------|
| `--user USER`         | Override the submitting user. Defaults to `$USER` env var.        |
| `-p KEY=VALUE`        | Override a job parameter. Repeatable. See [Parameters](#parameters). |
| `--min-cores N`       | Override minimum CPU cores for **all** layers.                    |
| `--max-cores N`       | Override maximum CPU cores for **all** layers.                    |
| `--min-memory N`      | Override minimum memory (MB) for **all** layers.                  |

### Output mode flags (mutually exclusive)

| Flag          | Description                                                     |
|---------------|-----------------------------------------------------------------|
| `--dry-run`   | Print what would be submitted. Nothing is sent to OpenCue.      |
| `--emit-code` | Print a standalone PyOutline Python script to stdout.            |
| *(neither)*   | Submit directly to OpenCue via PyOutline.                        |

### Full examples

```bash
# Dry-run with all defaults
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 --dry-run

# Override two parameters
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 \
    -p SceneFile=/scenes/shot.blend \
    -p FrameEnd=200

# Force all layers to use at least 8 cores and 16GB RAM
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 \
    --min-cores 8 --min-memory 16384

# Generate a Python submission script you can check into git
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 \
    --emit-code > submit_sh010.py

# Submit to a specific Cuebot
CUEBOT_HOSTS=cuebot.farm.local \
    python openjd_to_opencue.py job.yaml --show myshow --shot sh010
```

---

## Template Authoring Guide

Templates are YAML (or JSON) files following the OpenJD `jobtemplate-2023-09` specification. Below is a reference for every feature this converter supports.

### Minimal Template

The absolute minimum is a spec version, a name, and one step with a command:

```yaml
specificationVersion: jobtemplate-2023-09
name: MyJob
steps:
  - name: DoWork
    script:
      actions:
        onRun:
          command: echo
          args: ["hello"]
```

This creates a single-frame job (frame 1) that runs `echo hello`.

### Job Name

```yaml
name: "Render_{{Param.ShotName}}_v{{Param.Version}}"
```

The name can include `{{Param.X}}` references that get resolved at submission time. Special characters are replaced with underscores to keep OpenCue happy.

### Parameters

Parameters are variables you define in the template and resolve at submission time. They let you reuse one template across different shots, scenes, or frame ranges.

```yaml
parameterDefinitions:
  # With a default — can be overridden with -p but doesn't have to be
  - name: SceneFile
    type: PATH
    default: /scenes/default.blend

  # Without a default — MUST be provided with -p at submission time
  - name: InputFile
    type: PATH

  # Supported types: STRING, INT, FLOAT, PATH
  - name: FrameStart
    type: INT
    default: 1
  - name: FrameEnd
    type: INT
    default: 100
  - name: Quality
    type: FLOAT
    default: 0.9
  - name: ShotName
    type: STRING
    default: sh010
```

**Override at the CLI:**

```bash
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 \
    -p InputFile=/path/to/file.mov \
    -p FrameEnd=200 \
    -p Quality=0.95
```

**Resolution priority:** CLI `-p` value > template `default`. If a parameter has no default and isn't provided via `-p`, the converter raises an error.

### Steps

Each step becomes an OpenCue layer. Steps are defined as a list and are processed in order:

```yaml
steps:
  - name: Render        # → OpenCue layer "Render"
    # ... (parameterSpace, script, dependencies, hostRequirements)

  - name: Composite     # → OpenCue layer "Composite"
    # ...
```

Step names must be unique within a template. They're sanitised to `[a-zA-Z0-9_-]` for OpenCue compatibility.

### Frame Ranges (parameterSpace)

The `parameterSpace` defines how a step is split into individual tasks (frames in OpenCue).

**Basic frame range:**

```yaml
parameterSpace:
  taskParameterDefinitions:
    - name: Frame
      type: INT
      range: "1-100"
```

This creates 100 frames (1 through 100).

**Range with step (every 5th frame):**

```yaml
    range: "1-100:5"    # OpenJD syntax — colon means step
                         # Converted to "1-100x5" for OpenCue
```

**Dynamic range from job parameters:**

```yaml
    range: "{{Param.FrameStart}}-{{Param.FrameEnd}}"
```

The `{{Param.X}}` references are resolved before the range is passed to OpenCue.

**Chunk size** (process N frames per task):

```yaml
parameterSpace:
  taskParameterDefinitions:
    - name: Frame
      type: INT
      range: "1-1000"
  chunkSize: 10          # Each OpenCue frame processes 10 frames
```

**No parameterSpace** (single task):

If you omit `parameterSpace` entirely, the step becomes a single-frame layer (frame 1). This is useful for non-parallelisable steps like generating a final MOV or running a post-process script.

**The parameter name doesn't have to be "Frame"** — you can call it anything. The converter uses the first INT parameter it finds as the frame driver.

### Commands (script)

The command to execute is defined under `script.actions.onRun`:

```yaml
script:
  actions:
    onRun:
      command: blender                              # The executable
      args:                                          # Arguments as a list
        - "-b"
        - "{{Param.SceneFile}}"                     # Resolved job param
        - "-f"
        - "{{Task.Param.Frame}}"                    # Becomes #IFRAME#
```

The converter flattens `command` + `args` into a single command list. Parameter substitutions happen automatically:

- `{{Param.X}}` → resolved to the parameter's value
- `{{RawParam.X}}` → same (path remapping not implemented)
- `{{Task.Param.Frame}}` → replaced with `#IFRAME#` (OpenCue's per-frame token, substituted by RQD at execution time)

### Dependencies

Steps can depend on other steps. A dependent step won't start until all frames of the step it depends on have completed:

```yaml
steps:
  - name: Render
    # ...

  - name: Composite
    dependencies:
      - dependsOn: Render      # Won't start until all Render frames finish
    # ...

  - name: Dailies
    dependencies:
      - dependsOn: Composite   # Won't start until all Composite frames finish
    # ...
```

Dependencies are converted to PyOutline's `depend_on()` calls. Both forward and backward references work (a step can reference any other step in the template, regardless of order).

### Resource Requirements (hostRequirements)

Control how much CPU and memory each step needs, and which hosts it can run on:

```yaml
hostRequirements:
  # Numeric requirements → OpenCue min/max cores and memory
  amounts:
    - name: amount.worker.vcpu
      min: 4                    # → layer.set_min_cores(4)
      max: 16                   # → layer.set_max_cores(16)
    - name: amount.worker.memory
      min: 8192                 # → layer.set_min_memory(8192)  (MB)

  # Categorical requirements → OpenCue tags
  attributes:
    - name: attr.worker.os.family
      anyOf: ["linux"]          # → tag "linux" on the layer
    - name: attr.worker.gpu
      anyOf: ["nvidia"]         # → tag "nvidia" on the layer
```

**Name matching is keyword-based:** any amount name containing `vcpu`, `cpu`, or `core` maps to cores; `memory` or `ram` maps to memory. Everything else becomes a tag.

**CLI overrides** (`--min-cores`, `--max-cores`, `--min-memory`) take precedence over template values and apply to all layers uniformly.

### Environment Variables

Simple key-value environment variables can be set via `script.variables`:

```yaml
script:
  variables:
    MAYA_LOCATION: /usr/autodesk/maya2024
    RENDER_QUALITY: "{{Param.Quality}}"
  actions:
    onRun:
      command: maya
      args: ["-batch", "-file", "{{Param.SceneFile}}"]
```

These are passed to PyOutline via `layer.set_env()`. Parameter references in values are resolved.

> **Note:** This is different from OpenJD's `stepEnvironments` / `jobEnvironments` which have `onEnter`/`onExit` lifecycle hooks. Those are **not supported** in this version — only `script.variables` is.

---

## Format Strings Reference

OpenJD uses `{{ }}` double-brace syntax for variable substitution. Here's how each scope is handled:

| Syntax                    | Scope       | Resolved When       | Becomes in OpenCue                |
|---------------------------|-------------|---------------------|-----------------------------------|
| `{{Param.X}}`             | Job param   | At conversion time  | Literal resolved value            |
| `{{RawParam.X}}`          | Job param   | At conversion time  | Literal resolved value (same)     |
| `{{Task.Param.Frame}}`    | Task param  | At execution time   | `#IFRAME#` (RQD substitutes)     |

**Example transformation:**

Template:
```yaml
args:
  - "{{Param.OutputDir}}/render_{{Task.Param.Frame}}.exr"
```

With `-p OutputDir=/renders/sh010`, becomes:
```
/renders/sh010/render_#IFRAME#.exr
```

At execution time, OpenCue's RQD replaces `#IFRAME#` with the actual frame number (e.g., `1`, `2`, `1001`, etc.).

---

## How the Concept Mapping Works

```
┌──────────────────────────────────────────────────────────────────────┐
│                         OpenJD Template                              │
│                                                                      │
│  specificationVersion: jobtemplate-2023-09                           │
│  name: "MyJob"                         ──────► Job name              │
│  parameterDefinitions:                 ──────► Resolved at CLI       │
│  steps:                                                              │
│    - name: Render                      ──────► Layer "Render"        │
│      parameterSpace:                                                 │
│        taskParameterDefinitions:                                     │
│          - name: Frame                                               │
│            range: "1-100"              ──────► Frame range "1-100"   │
│      dependencies:                                                   │
│        - dependsOn: Preprocess         ──────► depend_on(preprocess) │
│      hostRequirements:                                               │
│        amounts:                                                      │
│          - name: amount.worker.vcpu                                  │
│            min: 4                      ──────► set_min_cores(4)      │
│      script:                                                         │
│        actions:                                                      │
│          onRun:                                                      │
│            command: blender            ──────► Command list           │
│            args: ["-f", "{{Task...}}"] ──────► [..., "#IFRAME#"]     │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      OpenCue (via PyOutline)                         │
│                                                                      │
│  job = Outline(name="MyJob", show="...", shot="...")                 │
│  layer = Shell(name="Render", command=[...], range="1-100")         │
│  layer.set_min_cores(4)                                              │
│  layer.depend_on(preprocess_layer)                                   │
│  job.add_layer(layer)                                                │
│  job.setup()                                                         │
│  job.launch()                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### Quick reference table

| OpenJD Concept         | OpenCue Equivalent          | Notes                                  |
|------------------------|-----------------------------|----------------------------------------|
| Job Template           | Outline (job)               | show/shot added at CLI                 |
| Step                   | Layer                       | 1:1 mapping                            |
| Task                   | Frame                       | Driven by first INT param              |
| parameterSpace range   | Frame range string          | `:` step → `x` step                   |
| chunkSize              | chunk                       | Frames per task                        |
| dependencies           | depend_on()                 | Layer-to-layer                         |
| hostRequirements       | min_cores / min_memory / tags | Keyword-matched                      |
| `{{Param.X}}`          | Resolved literal            | Before submission                      |
| `{{Task.Param.Frame}}` | `#IFRAME#`                  | RQD substitutes at runtime             |
| script.onRun           | Shell command               | command + args flattened               |
| script.variables       | set_env()                   | Per-layer env vars                     |
| Environments (onEnter) | *(not supported)*           | v1 limitation                          |
| Path remapping         | *(not supported)*           | v1 limitation                          |

---

## Worked Examples

### Example 1: Hello World

**Template** (`examples/hello_world.yaml`):

```yaml
specificationVersion: jobtemplate-2023-09
name: "HelloWorld"
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
```

**What happens:**
- No `parameterDefinitions` → no job-level params to resolve
- One step `SayHello` → one OpenCue layer
- `range: "1-10"` → 10 frames
- `{{Task.Param.Frame}}` → `#IFRAME#`
- Each frame runs: `echo hello world - frame 1`, `echo hello world - frame 2`, etc.

**Command:**
```bash
python openjd_to_opencue.py examples/hello_world.yaml \
    --show testshow --shot test01 --dry-run
```

---

### Example 2: FFmpeg Transcode with Dependencies

**Template** (`examples/ffmpeg_transcode.yaml`):

```yaml
specificationVersion: jobtemplate-2023-09
name: "Transcode_{{Param.JobLabel}}"

parameterDefinitions:
  - name: InputFile
    type: PATH                  # No default — must be provided with -p
  - name: OutputDir
    type: PATH
    default: /deliveries/transcodes
  - name: JobLabel
    type: STRING
    default: transcode_job

steps:
  - name: h264
    script:
      actions:
        onRun:
          command: ffmpeg
          args:
            - "-y"
            - "-i"
            - "{{Param.InputFile}}"
            - "-c:v"
            - "libx264"
            - "{{Param.OutputDir}}/{{Param.JobLabel}}_h264.mp4"

  - name: webm_proxy
    dependencies:
      - dependsOn: h264         # Won't start until h264 finishes
    script:
      actions:
        onRun:
          command: ffmpeg
          args:
            - "-y"
            - "-i"
            - "{{Param.OutputDir}}/{{Param.JobLabel}}_h264.mp4"
            - "-c:v"
            - "libvpx-vp9"
            - "{{Param.OutputDir}}/{{Param.JobLabel}}_proxy.webm"
```

**What happens:**
- `InputFile` has no default → you must provide `-p InputFile=...`
- Job name contains `{{Param.JobLabel}}` → resolves to `Transcode_transcode_job`
- Two steps with no `parameterSpace` → two single-frame layers
- `webm_proxy` depends on `h264` → runs sequentially

**Command:**
```bash
python openjd_to_opencue.py examples/ffmpeg_transcode.yaml \
    --show commercials --shot spot_01 --dry-run \
    -p InputFile=/media/master/spot_01.mov
```

**Key takeaway:** Steps without a `parameterSpace` become single-frame layers (frame 1). This is perfect for non-parallelisable work like transcoding, archiving, or notification scripts.

---

### Example 3: Multi-Step VFX Pipeline

**Template** (`examples/multi_step_pipeline.yaml`) defines a 4-step chain:

```
Render (120 frames, 8 cores, 16GB, linux-only)
  └─► Denoise (120 frames, 4 cores, 8GB)
        └─► Composite (120 frames, 4 cores, 12GB)
              └─► Dailies (single task, 2 cores, 4GB)
```

**Command:**
```bash
python openjd_to_opencue.py examples/multi_step_pipeline.yaml \
    --show feature_film --shot sh030 --dry-run
```

**Key takeaway:** Dependencies cascade — Dailies won't start until Composite is done, which won't start until Denoise is done, which won't start until Render is done. Each step has its own resource requirements. The final Dailies step has no `parameterSpace` so it runs as a single task.

---

## Output Modes

### 1. `--dry-run` (start here)

Prints a human-readable summary. Use this to verify your template before submitting.

```bash
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 --dry-run
```

### 2. `--emit-code` (for inspection or version control)

Generates a standalone PyOutline Python script. You can pipe it to a file, review it, modify it, and run it later.

```bash
# Save to file
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 \
    --emit-code > submit_sh010.py

# Review
cat submit_sh010.py

# Run it later (requires pycue/pyoutline)
python submit_sh010.py
```

This is especially useful for debugging — you can see exactly what PyOutline calls are being made.

### 3. Default (live submission)

Submits directly to OpenCue. Requires `pycue`, `pyoutline`, and `CUEBOT_HOSTS`.

```bash
export CUEBOT_HOSTS=cuebot.farm.local
python openjd_to_opencue.py job.yaml --show myshow --shot sh010
# → "Submitted job 'MyJob' to OpenCue (3 layers)"
```

---

## Troubleshooting

### "ERROR: PyYAML is required"

```bash
pip install pyyaml
```

### "ERROR: OpenCue libraries not found"

You're trying to submit (no `--dry-run` or `--emit-code` flag) without the OpenCue Python packages:

```bash
pip install pycue pyoutline
```

### "WARNING: CUEBOT_HOSTS not set"

The script doesn't know where your Cuebot server is:

```bash
export CUEBOT_HOSTS=cuebot.yourstudio.com
```

### "Job parameter 'X' has no default and was not provided via --param / -p"

The template declares a parameter without a default value. You need to provide it:

```bash
python openjd_to_opencue.py job.yaml --show myshow --shot sh010 \
    -p X=some_value
```

### "Unsupported specificationVersion"

This converter only supports `jobtemplate-2023-09` (the current and only published OpenJD spec version). Check your template's `specificationVersion` field.

### "Step 'X' depends on unknown step 'Y'"

Your dependency references a step name that doesn't exist. Check for typos in `dependsOn` — it must exactly match a step's `name` field.

### Job submits but frames fail with "command not found"

The command in your template isn't available on the render hosts. Make sure the executable is in `$PATH` on every RQD host, or use an absolute path in your template:

```yaml
command: /usr/local/bin/blender    # Absolute path — more reliable
```

### Frame range shows "1-1" when I expected a range

Your step is missing a `parameterSpace` definition. Without one, the converter treats the step as a single task. Add a `parameterSpace` with a `taskParameterDefinitions` entry.

---

## Architecture

The converter works in three phases:

```
  ┌──────────────────────┐
  │  YAML/JSON Template  │
  └─────────┬────────────┘
            │
  Phase 1   │  load_template()     — parse file
            │  validate_template() — check structure
            ▼
  ┌──────────────────────┐
  │   Parsed Template    │
  │      (dict)          │
  └─────────┬────────────┘
            │
  Phase 2   │  convert_template()  — orchestrates:
            │    ├─ resolve_job_parameters()
            │    ├─ extract_frame_info()
            │    ├─ build_command()
            │    └─ extract_resources()
            ▼
  ┌──────────────────────┐
  │   ConvertedJob       │    Intermediate representation.
  │   ├─ ConvertedLayer  │    Independent of both OpenJD
  │   ├─ ConvertedLayer  │    and OpenCue data structures.
  │   └─ ...             │
  └─────────┬────────────┘
            │
  Phase 3   ├─► print_dry_run()        (--dry-run)
            ├─► emit_pyoutline_code()  (--emit-code)
            └─► submit_to_opencue()    (default)
```

The key design decision is the **intermediate representation** (`ConvertedJob` / `ConvertedLayer`). By converting into a clean data structure that doesn't depend on either library, all three output modes are straightforward and testable independently.

---

## Limitations & Roadmap

### What's NOT supported in v1

| Feature                         | Why                                              | Workaround                                  |
|---------------------------------|--------------------------------------------------|---------------------------------------------|
| Environment hooks (onEnter/onExit) | OpenCue has no session lifecycle concept        | Put setup/teardown in your onRun command    |
| Environment Templates (.env.yaml)  | Only Job Templates are parsed                  | Inline environment config into the job template |
| Multi-dimensional parameter spaces | Only first INT param drives frames             | Use a wrapper script to map frame → params  |
| Path remapping                   | Not implemented                                 | Use consistent mount points across farm      |
| Embedded files                   | OpenJD inline script content not parsed         | Use external scripts referenced by path      |
| Per-frame dependencies           | OpenCue layer deps are all-or-nothing           | Split into separate steps if needed          |

### Potential future additions

- **`--validate-only`** flag — just check the template, don't convert
- **Environment hook support** — flatten onEnter/onExit into pre/post wrapper scripts
- **Template inheritance** — compose jobs from reusable template fragments
- **OpenCue service mapping** — map OpenJD attributes to OpenCue service types
- **JSON Schema validation** — validate templates against the official OpenJD JSON schema via `openjd-model`
- **Batch submission** — submit multiple templates in one invocation

---

## Upstream Projects

| Project | What It Is | Links |
|---------|-----------|-------|
| **OpenCue** | Open-source render management system (ASWF) | [GitHub](https://github.com/AcademySoftwareFoundation/OpenCue) · [Docs](https://docs.opencue.io/) |
| **Open Job Description** | Portable job specification (AWS) | [GitHub](https://github.com/OpenJobDescription/openjd-specifications) · [Wiki](https://github.com/OpenJobDescription/openjd-specifications/wiki) |
| **openjd-model** | Python data model for OpenJD templates | [GitHub](https://github.com/OpenJobDescription/openjd-model-for-python) |
| **openjd-sessions** | Python runtime for OpenJD sessions | [GitHub](https://github.com/OpenJobDescription/openjd-sessions-for-python) |
| **openjd-cli** | CLI for validating/running OpenJD templates | [GitHub](https://github.com/OpenJobDescription/openjd-cli) |
| **PyOutline** | OpenCue's Python job-building library | [GitHub](https://github.com/AcademySoftwareFoundation/OpenCue/tree/master/pyoutline) |

---

## License

Apache-2.0
