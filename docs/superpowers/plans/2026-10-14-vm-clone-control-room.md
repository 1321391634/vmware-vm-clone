# vm-clone Control Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce vm-clone's onefile EXE size and redesign its Qt interface as the approved B-style bright control room.

**Architecture:** Keep the domain and VMware contracts stable. Replace heavyweight report and credential dependencies with small local adapters, then restyle the existing main window, inventory panel, wizard and controls around a shared design token system.

**Tech Stack:** Python 3.11, PySide6, pyVmomi, standard-library ZIP/XML/ctypes, PyInstaller, pytest.

---

### Task 1: Replace heavyweight report and credential dependencies

**Files:**
- Create: `app/reports/xlsx_writer.py`
- Create: `app/persistence/windows_secrets.py`
- Modify: `app/reports/exporter.py`
- Modify: `app/persistence/credentials.py`
- Modify: `requirements.txt`
- Modify: `tests/test_execution.py`, `tests/test_persistence.py`

- [x] Write failing tests for a valid minimal XLSX package and DPAPI-backed credential storage.
- [x] Run the focused tests and confirm they fail because the new adapters do not exist.
- [x] Implement standard-library XLSX generation with two sheets and XML escaping.
- [x] Implement Windows DPAPI encryption/decryption and metadata-only profile storage.
- [x] Remove `openpyxl` and `keyring` from runtime requirements and imports.
- [x] Run focused and full tests.

### Task 2: Reduce PyInstaller collection

**Files:**
- Modify: `vm-clone.spec`
- Modify: `build.ps1`
- Modify: `.gitignore`

- [x] Add explicit excludes for unused Qt modules and optional packages.
- [x] Make the build script use the checked-in spec and report the output size.
- [x] Ensure build artifacts and brainstorming files are ignored.
- [x] Run PyInstaller and record the final EXE size.

### Task 3: Rebuild the shared Qt visual system

**Files:**
- Modify: `app/ui/styles.py`
- Modify: `app/ui/widgets.py`
- Modify: `tests/test_ui_smoke.py`

- [x] Add smoke assertions for the control-room object names and status elements.
- [x] Implement shared spacing, warm-white surfaces, typography, selected/hover/disabled states and compact controls.
- [x] Add reusable section header, status badge and metric label primitives where they remove duplication.
- [x] Run UI smoke tests in offscreen mode.

### Task 4: Redesign inventory and wizard layout

**Files:**
- Modify: `app/ui/inventory_panel.py`
- Modify: `app/ui/wizard_panel.py`
- Modify: `app/ui/main_window.py`

- [x] Add test coverage for inventory empty state and selected VM summary.
- [x] Implement the new top bar, inventory header/filter hierarchy, step rail and bottom preview presentation.
- [x] Keep all current form signals and domain validation behavior intact.
- [x] Render an offscreen screenshot at desktop dimensions and inspect it visually.

### Task 5: Final verification and handoff

**Files:**
- Modify: `README.md`

- [x] Run all tests and compile checks.
- [x] Build onefile EXE from the spec.
- [x] Start the EXE for a short smoke interval and clean up the process.
- [x] Confirm all changes are under `vm-clone` and report the size comparison.
