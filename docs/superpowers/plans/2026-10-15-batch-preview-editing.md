# Batch Preview Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the batch preview the editable source of truth for per-VM clone settings, replace fragile IPv4 auto-fill with start/end address calculation, and keep the effective values flowing into vCenter, reports, and retries.

**Architecture:** Keep batch-wide values in `ClonePlan`, add immutable effective resource fields to each `CloneItem`, and rebuild a validated plan after preview edits. The Qt preview will use embedded editors and retain row drafts by sequence; it will only publish a new plan after domain validation succeeds. The VMware gateway will accept the item-level effective storage, port group, CPU, memory, and disk list while retaining batch-wide folder, compute, customization, network policy, remark, power, and concurrency behavior.

**Tech Stack:** Python 3, PySide6 Qt Widgets, pyVmomi, pytest, openpyxl.

---

### Task 1: Define item-level effective configuration and IPv4 boundaries

**Files:**
- Modify: `app/domain/models.py`
- Modify: `app/domain/validation.py`
- Test: `tests/test_domain.py`

- [x] **Step 1: Write failing domain tests** for `ipv4_range_end("192.168.1.191", 3)`, IPv4 overflow, default empty disks, and generated items carrying inherited storage/port group/CPU/memory/disk values.
- [x] **Step 2: Run the focused tests** and confirm they fail because the end-address helper and item-level fields do not exist.
- [x] **Step 3: Implement the minimum model and validation changes:** add `datastore_name`, `portgroup_name`, `cpu_count`, `memory_gb`, and `disk_requests` to `CloneItem` with compatibility defaults; add `ipv4_range_end()` using `ipaddress.IPv4Address` integer arithmetic; make generated item disk lists empty unless disks were explicitly supplied.
- [x] **Step 4: Run the focused domain tests** and confirm they pass without changing existing validation semantics.

### Task 2: Build and validate edited batch items in the domain layer

**Files:**
- Modify: `app/domain/planning.py`
- Test: `tests/test_domain.py`

- [x] **Step 1: Write failing tests** that apply different row values for storage, port group, CPU, memory, disks, names, hostnames, and IPs, and tests that reject duplicate names/IPs, missing resources, non-positive CPU/memory, and invalid disk values.
- [x] **Step 2: Run the tests** and confirm the row-edit API is missing or rejects the new fields.
- [x] **Step 3: Implement `apply_clone_item_edits(plan, edited_items, inventory)`**: normalize and validate every row, preserve batch-level fields, recompute conflict warnings, and return a new immutable plan whose items are the validated effective values.
- [x] **Step 4: Run domain and preflight tests** and confirm original behavior plus the new row-edit behavior pass.

### Task 3: Make the VMware gateway consume per-item settings

**Files:**
- Modify: `app/vmware/clone_gateway.py`
- Test: `tests/test_clone_gateway.py`

- [x] **Step 1: Write failing gateway tests** that create a plan with two items having different datastore, port group, CPU, memory, and disk values, then assert each `CloneVM_Task` receives its own effective settings.
- [x] **Step 2: Run the focused gateway tests** and confirm the gateway still reads batch-level fields.
- [x] **Step 3: Update config-spec construction, datastore lookup, logging, and network selection** to use the passed `CloneItem`; retain direct returned-VM power-on, DVS backing construction, inherited DVS port cleanup, timeout handling, and customization behavior.
- [x] **Step 4: Run all gateway and execution tests** and verify retry execution reuses the same edited item configuration.

### Task 4: Replace the IPv4 UI and make empty-disk behavior immediate

**Files:**
- Modify: `app/ui/wizard_panel.py`
- Modify: `app/ui/widgets.py` if an editor helper is needed
- Test: `tests/test_ui_smoke.py`

- [x] **Step 1: Write failing Qt tests** for separate editable start/end fields, `192.168.1.191` plus quantity 3 producing `.193`, an initially empty disk list, and preview refresh immediately after removing the last disk.
- [x] **Step 2: Run the focused Qt tests** and confirm the current one-field IPv4 UI and default disk row fail the new expectations.
- [x] **Step 3: Implement the two-field IPv4 flow** with a read-only calculated end field, use the domain helper, remove cached string-prefix state, and preserve the range in `NetworkConfig.ip_input` for compatibility.
- [x] **Step 4: Remove default disk initialization** and ensure add/remove operations rebuild the preview immediately while preserving an empty tuple as “no added disk.”
- [x] **Step 5: Run the focused Qt tests** and confirm the UI state is stable after every signal-driven refresh.

### Task 5: Add an editable preview editor with searchable resources

**Files:**
- Create: `app/ui/preview_editor.py`
- Modify: `app/ui/wizard_panel.py`
- Modify: `app/ui/widgets.py`
- Test: `tests/test_ui_smoke.py`

- [x] **Step 1: Write failing Qt tests** that edit one row independently, verify storage and port group use searchable combo boxes, and verify refreshing another field does not discard existing row drafts.
- [x] **Step 2: Run the focused tests** and confirm the current read-only table fails.
- [x] **Step 3: Implement a focused preview editor** that stores drafts by sequence, creates line edits, searchable combos, spin boxes, and a disk editor action, and emits an edit signal without rebuilding away user input.
- [x] **Step 4: Integrate editor drafts with `apply_clone_item_edits()`** so invalid edits leave the last valid plan active and display row/field errors; valid edits update `current_plan` and `plan_changed`.
- [x] **Step 5: Run all UI tests** and confirm the table displays complete values without ellipsis and supports horizontal scrolling.

### Task 6: Include effective row settings in reports

**Files:**
- Modify: `app/reports/models.py`
- Modify: `app/reports/exporter.py`
- Test: `tests/test_execution.py`

- [x] **Step 1: Write failing JSON/Excel tests** asserting per-row datastore, port group, CPU, memory, and disk details are exported.
- [x] **Step 2: Run the focused report tests** and confirm the fields are absent.
- [x] **Step 3: Add effective item fields to JSON and Excel result rows** while retaining existing batch summary fields and warning/status data.
- [x] **Step 4: Run report and execution tests** and verify the report reflects the same item configuration sent to the gateway.

### Task 7: Full regression, packaging, and acceptance checks

**Files:**
- Modify: `README.md` only if the user-facing IPv4 or preview behavior needs documentation
- Modify: `build.ps1` only if packaging verification exposes a real packaging issue

- [x] **Step 1: Run the full pytest suite** from `vm-clone` and inspect every failure rather than weakening tests.
- [x] **Step 2: Run `python -m compileall -q app main.py`** to catch import and syntax errors.
- [x] **Step 3: Run `build.ps1`** and verify a single-file `dist/vm-clone.exe` is produced.
- [x] **Step 4: Run a clean UI smoke check** with `QT_QPA_PLATFORM=offscreen` and verify the executable's entry point imports without a Python source path dependency.
- [x] **Step 5: Review the final diff** and confirm no file outside `vm-clone` changed and no existing automatic power-on, hostname customization, DVS, retry, or timeout logic was removed.
