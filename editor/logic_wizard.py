"""
Logic Wizard
============
A guided QWizard that lets you wire up common I/O scenarios without
touching the raw connection editor.

Six built-in scenarios:
  1. Locked Room       — monster wakes when door opens
  2. Alarm System      — monster seeing player triggers a speaker
  3. Chain Reaction    — killing one monster wakes another
  4. Death Trap        — monster death opens a door
  5. Kill the Lights   — monster spots player → lights off
  6. Timed Patrol      — logic_timer fires → monster wakes

Usage
-----
  from editor.logic_wizard import LogicWizard
  wiz = LogicWizard(editor_state, graph_scene, parent=window)
  if wiz.exec_() == QDialog.Accepted:
      ...  # connections added to graph_scene; call apply_to_entities() to save
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any

from PyQt5.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QDoubleSpinBox, QCheckBox, QFormLayout,
    QGroupBox, QListWidget, QListWidgetItem,
    QWidget, QSpinBox, QApplication, QMessageBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui  import QFont, QFontMetrics

try:
    from .io_system import get_entity_type_for_io, IO_REGISTRY
    IO_AVAILABLE = True
except ImportError:
    IO_AVAILABLE = False


# ── Scenario catalogue ────────────────────────────────────────────────────────

SCENARIOS: List[Dict[str, Any]] = [
    {
        "id":    "locked_room",
        "title": "Locked Room",
        "icon":  "🚪",
        "short": "Monster sleeps until a door opens",
        "desc":  (
            "A monster starts dormant (triggered=True) and only wakes "
            "when a door is opened via another trigger or by the player. "
            "Great for ambushes behind unlocked doors."
        ),
        "wiring": [
            # (source_role, out_pin, target_role, in_pin, description)
            ("door", "OnOpen", "monster", "Wake",
             "Door opens → Monster wakes"),
        ],
        "roles": [
            ("door",    "door",    "The door that unlocks the monster"),
            ("monster", "monster", "The monster to wake"),
        ],
        "params": [],
    },
    {
        "id":    "alarm_system",
        "title": "Alarm System",
        "icon":  "🔔",
        "short": "Monster spotting the player triggers an alarm sound",
        "desc":  (
            "When the monster first sees the player it fires OnSeePlayer, "
            "which starts a speaker (alarm, music, etc.). "
            "A second connection stops the alarm when the monster loses sight."
        ),
        "wiring": [
            ("monster", "OnSeePlayer",  "speaker", "PlaySound",
             "Monster sees player → Speaker plays"),
            ("monster", "OnLostPlayer", "speaker", "StopSound",
             "Monster loses sight → Speaker stops"),
        ],
        "roles": [
            ("monster", "monster", "The monster watching for the player"),
            ("speaker", "speaker", "The speaker / alarm to activate"),
        ],
        "params": [],
    },
    {
        "id":    "chain_reaction",
        "title": "Chain Reaction",
        "icon":  "💥",
        "short": "Killing one monster wakes another",
        "desc":  (
            "When the first monster dies (OnDeath) it sends a Wake signal "
            "to a second dormant monster.  Chain as many as you like by "
            "applying the wizard repeatedly."
        ),
        "wiring": [
            ("monster_a", "OnDeath", "monster_b", "Wake",
             "Monster A dies → Monster B wakes"),
        ],
        "roles": [
            ("monster_a", "monster", "The monster that triggers on death"),
            ("monster_b", "monster", "The monster to wake"),
        ],
        "params": [],
    },
    {
        "id":    "death_trap",
        "title": "Death Trap",
        "icon":  "⚙",
        "short": "Monster death opens a door or activates a mover",
        "desc":  (
            "Killing a monster opens a door (or fires any connected mover). "
            "Use this for 'kill the guard to open the vault' moments."
        ),
        "wiring": [
            ("monster", "OnDeath", "door", "Open",
             "Monster dies → Door opens"),
        ],
        "roles": [
            ("monster", "monster", "The monster that must be killed"),
            ("door",    "door",    "The door/mover to activate"),
        ],
        "params": [],
    },
    {
        "id":    "kill_lights",
        "title": "Kill the Lights",
        "icon":  "💡",
        "short": "Monster spotting player turns off a light",
        "desc":  (
            "The moment a monster first sees the player it fires OnSeePlayer, "
            "triggering a light to turn off.  Pair with an ambient speaker "
            "for a jump-scare atmosphere."
        ),
        "wiring": [
            ("monster", "OnSeePlayer",  "light", "TurnOff",
             "Monster sees player → Light turns off"),
            ("monster", "OnLostPlayer", "light", "TurnOn",
             "Monster loses sight → Light back on"),
        ],
        "roles": [
            ("monster", "monster", "The monster watching the area"),
            ("light",   "light",   "The light to extinguish"),
        ],
        "params": [],
    },
    {
        "id":    "timed_patrol",
        "title": "Timed Patrol",
        "icon":  "⏱",
        "short": "A timer wakes a dormant monster after N seconds",
        "desc":  (
            "A LogicTimer fires repeatedly (or once) and sends Wake to a "
            "monster.  Set the timer interval in Properties to control the delay. "
            "Use fire_once on the connection to wake only once."
        ),
        "wiring": [
            ("timer", "OnTimer", "monster", "Wake",
             "Timer fires → Monster wakes"),
        ],
        "roles": [
            ("timer",   "logic_timer", "The timer that controls the delay"),
            ("monster", "monster",     "The monster to patrol"),
        ],
        "params": [
            {
                "key":     "fire_once",
                "label":   "Wake only once",
                "type":    "bool",
                "default": True,
                "help":    "If checked the connection fires once; otherwise re-wakes every interval.",
            }
        ],
    },
]


# ── Wizard stylesheet ─────────────────────────────────────────────────────────
#
# No font-size: Npx values anywhere.  All text inherits from QApplication.font()
# so it respects the user's font_size setting in Settings and OS DPI scaling.

WIZARD_STYLE = """
QWizard, QWizardPage {
    background: #1e1e24;
    color: #ddd;
    font-family: 'Segoe UI', Arial;
}
QLabel { color: #ccc; }
QComboBox {
    background: #2e2e38;
    border: 1px solid #555;
    color: #eee;
    padding: 4px;
    min-width: 180px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background: #2e2e38; color: #eee; }
QDoubleSpinBox, QSpinBox {
    background: #2e2e38;
    border: 1px solid #555;
    color: #eee;
    padding: 3px;
}
QCheckBox { color: #ccc; spacing: 6px; }
QGroupBox {
    color: #bbb;
    border: 1px solid #444;
    border-radius: 5px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #aaa;
}
QListWidget {
    background: #252530;
    border: 1px solid #444;
    color: #ddd;
    outline: none;
}
QListWidget::item {
    padding: 8px 10px;
    border-bottom: 1px solid #333;
}
QListWidget::item:selected {
    background: #2a3a5a;
    color: #fff;
    border-left: 3px solid #4a90d9;
}
QListWidget::item:hover { background: #2a2a38; }
QPushButton {
    background: #3a3a44;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 6px 14px;
    color: #ddd;
}
QPushButton:hover { background: #4a4a55; }
"""


# ── Page 1 — Scenario selection ───────────────────────────────────────────────

class ScenarioPage(QWizardPage):
    """Choose a scenario from the built-in catalogue."""

    PAGE_ID = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Choose a Scenario")
        self.setSubTitle(
            "Select a pre-built wiring pattern. "
            "You will pick the specific entities on the next page."
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._list = QListWidget()
        self._list.setIconSize(QSize(32, 32))
        self._list.currentRowChanged.connect(self._on_select)

        for sc in SCENARIOS:
            item = QListWidgetItem(f"  {sc['icon']}  {sc['title']}")
            item.setData(Qt.UserRole, sc["id"])
            item.setToolTip(sc["desc"])
            self._list.addItem(item)

        layout.addWidget(self._list)

        # Description box
        self._desc_box = QGroupBox("Description")
        desc_lay = QVBoxLayout(self._desc_box)
        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        # Colour only — no font-size so it inherits from QApplication.font()
        self._desc_lbl.setStyleSheet("color: #aaa; padding: 4px;")
        desc_lay.addWidget(self._desc_lbl)
        layout.addWidget(self._desc_box)

        # Wiring preview
        self._wire_box = QGroupBox("Connections that will be created")
        wire_lay = QVBoxLayout(self._wire_box)
        self._wire_lbl = QLabel()
        self._wire_lbl.setWordWrap(True)
        # Use a monospace variant of the app font — no hardcoded point size
        mono = QFont(QApplication.font())
        mono.setFamily("Courier New")
        self._wire_lbl.setFont(mono)
        self._wire_lbl.setStyleSheet("color: #80c0ff;")
        wire_lay.addWidget(self._wire_lbl)
        layout.addWidget(self._wire_box)

        self._list.setCurrentRow(0)

        self.registerField("scenario_id*",
                           self._list, "currentRow",
                           self._list.currentRowChanged)

    def _on_select(self, row: int):
        if row < 0 or row >= len(SCENARIOS):
            return
        sc = SCENARIOS[row]
        self._desc_lbl.setText(sc["desc"])
        wires = "\n".join(
            f"  {w[0]}.{w[1]}  →  {w[2]}.{w[3]}"
            for w in sc["wiring"]
        )
        self._wire_lbl.setText(wires)

    def selected_scenario(self) -> Optional[Dict]:
        row = self._list.currentRow()
        if 0 <= row < len(SCENARIOS):
            return SCENARIOS[row]
        return None

    def isComplete(self) -> bool:
        return self._list.currentRow() >= 0


# ── Page 2 — Entity selection ─────────────────────────────────────────────────

class EntitiesPage(QWizardPage):
    """Pick the entity for each role in the chosen scenario."""

    PAGE_ID = 1

    def __init__(self, editor_state, parent=None):
        super().__init__(parent)
        self.editor_state = editor_state
        self.setTitle("Pick Entities")
        self.setSubTitle(
            "Choose the specific entity for each role. "
            "Only compatible entity types are shown."
        )
        self._combos: Dict[str, QComboBox] = {}
        self._layout = QFormLayout()
        layout = QVBoxLayout(self)
        self._role_group = QGroupBox("Roles")
        self._role_group.setLayout(self._layout)
        layout.addWidget(self._role_group)
        layout.addStretch()

    def initializePage(self):
        """Rebuild combo boxes for the chosen scenario each time this page is shown."""
        wiz = self.wizard()
        sc  = wiz.page(ScenarioPage.PAGE_ID).selected_scenario()
        if not sc:
            return

        # Clear previous widgets
        while self._layout.count():
            child = self._layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._combos.clear()

        self.setSubTitle(
            f"Scenario: {sc['icon']}  {sc['title']}\n"
            "Choose an entity for each role below."
        )

        for role_id, required_type, role_desc in sc["roles"]:
            combo = QComboBox()
            names = self._names_of_type(required_type)
            if not names:
                combo.addItem(f"⚠  No '{required_type}' entities found")
                combo.setEnabled(False)
            else:
                for n in names:
                    combo.addItem(n)
            self._combos[role_id] = combo

            lbl = QLabel(
                f"<b>{role_desc}</b><br>"
                f"<small style='color:#888;'>type: {required_type}</small>"
            )
            lbl.setWordWrap(True)
            self._layout.addRow(lbl, combo)

    def _names_of_type(self, required_type: str) -> List[str]:
        """Return all entity names whose IO type matches required_type."""
        results = []
        for t in self.editor_state.things:
            etype = get_entity_type_for_io(t) if IO_AVAILABLE else ""
            if required_type in (etype, etype.replace("_", "")):
                name = t.properties.get("name", "")
                if name:
                    results.append(name)
        for b in self.editor_state.brushes:
            btype = b.get("type", "")
            if required_type in (btype, btype.replace("_", "")):
                name = b.get("name", "")
                if name:
                    results.append(name)
        return results

    def entity_for_role(self, role_id: str) -> str:
        combo = self._combos.get(role_id)
        if combo and combo.isEnabled():
            return combo.currentText()
        return ""

    def isComplete(self) -> bool:
        return all(
            cb.isEnabled() and cb.currentText()
            for cb in self._combos.values()
        )


# ── Page 3 — Options ──────────────────────────────────────────────────────────

class OptionsPage(QWizardPage):
    """Fine-tune delay, fire-once, and any scenario-specific parameters."""

    PAGE_ID = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Connection Options")
        self.setSubTitle("Fine-tune the behaviour of the connections.")
        self._param_widgets: Dict[str, Any] = {}
        self._form = QFormLayout()
        layout = QVBoxLayout(self)

        # Global options — always shown
        global_grp  = QGroupBox("Global Options")
        global_form = QFormLayout(global_grp)

        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0.0, 60.0)
        self._delay_spin.setSingleStep(0.25)
        self._delay_spin.setSuffix(" sec")
        self._delay_spin.setValue(0.0)
        global_form.addRow("Trigger delay:", self._delay_spin)

        self._fire_once_chk = QCheckBox(
            "Connections fire only once per play session")
        self._fire_once_chk.setChecked(False)
        global_form.addRow("", self._fire_once_chk)

        layout.addWidget(global_grp)

        # Scenario-specific params (shown only when the scenario has params)
        self._specific_grp = QGroupBox("Scenario Options")
        self._specific_grp.setLayout(self._form)
        layout.addWidget(self._specific_grp)
        layout.addStretch()

    def initializePage(self):
        wiz = self.wizard()
        sc  = wiz.page(ScenarioPage.PAGE_ID).selected_scenario()
        if not sc:
            return

        # Clear previous scenario-specific widgets
        while self._form.count():
            child = self._form.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._param_widgets.clear()

        params = sc.get("params", [])
        self._specific_grp.setVisible(bool(params))

        for p in params:
            if p["type"] == "bool":
                w = QCheckBox(p["help"])
                w.setChecked(p["default"])
                self._form.addRow(p["label"] + ":", w)
                self._param_widgets[p["key"]] = w
            elif p["type"] == "float":
                w = QDoubleSpinBox()
                w.setValue(p["default"])
                w.setRange(p.get("min", 0.0), p.get("max", 999.0))
                w.setSuffix(p.get("suffix", ""))
                self._form.addRow(p["label"] + ":", w)
                self._param_widgets[p["key"]] = w

    def global_delay(self)     -> float: return self._delay_spin.value()
    def global_fire_once(self) -> bool:  return self._fire_once_chk.isChecked()

    def param_value(self, key: str) -> Any:
        w = self._param_widgets.get(key)
        if w is None:
            return None
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, (QDoubleSpinBox, QSpinBox)):
            return w.value()
        return None


# ── Page 4 — Summary ──────────────────────────────────────────────────────────

class SummaryPage(QWizardPage):
    """Preview exactly which connections will be added before committing."""

    PAGE_ID = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Summary")
        self.setSubTitle(
            "Review the connections that will be added to the Logic Graph.")
        layout = QVBoxLayout(self)

        self._summary_lbl = QLabel()
        self._summary_lbl.setWordWrap(True)
        # Use a monospace variant of the app font for the connection list.
        # No font-size: Npx — size is inherited from QApplication.font().
        mono = QFont(QApplication.font())
        mono.setFamily("Courier New")
        self._summary_lbl.setFont(mono)
        self._summary_lbl.setStyleSheet("""
            background: #1a1a22;
            border: 1px solid #3a3a50;
            border-radius: 4px;
            padding: 14px;
            color: #b0e0ff;
        """)
        layout.addWidget(self._summary_lbl)

        self._note_lbl = QLabel(
            "⚠  These connections are added to the Logic Graph but not yet "
            "saved to entities. Press <b>Apply</b> in the graph window to save."
        )
        self._note_lbl.setWordWrap(True)
        # Colour and spacing only — no font-size
        self._note_lbl.setStyleSheet("color: #a0a060; padding-top: 8px;")
        layout.addWidget(self._note_lbl)
        layout.addStretch()

    def initializePage(self):
        wiz = self.wizard()
        sc  = wiz.page(ScenarioPage.PAGE_ID).selected_scenario()
        ep  = wiz.page(EntitiesPage.PAGE_ID)
        op  = wiz.page(OptionsPage.PAGE_ID)
        if not sc or not ep or not op:
            return

        delay     = op.global_delay()
        fire_once = op.global_fire_once()

        lines = [f"<b>{sc['icon']}  {sc['title']}</b>", ""]
        for wire in sc["wiring"]:
            src_role, out_pin, dst_role, in_pin, _desc = wire
            src_name = ep.entity_for_role(src_role)
            dst_name = ep.entity_for_role(dst_role)

            fo = fire_once
            # Let scenario-level fire_once override the global one if present
            if "fire_once" in [p["key"] for p in sc.get("params", [])]:
                v = op.param_value("fire_once")
                if v is not None:
                    fo = bool(v)

            line = (
                f"  {src_name}<b>.{out_pin}</b>"
                f"  →  "
                f"{dst_name}<b>.{in_pin}</b>"
            )
            extras = []
            if delay > 0.0:
                extras.append(f"delay {delay:.2f}s")
            if fo:
                extras.append("fire once")
            if extras:
                line += f"  <span style='color:#888'>({', '.join(extras)})</span>"
            lines.append(line)

        self._summary_lbl.setText("<br>".join(lines))


# ── Wizard ────────────────────────────────────────────────────────────────────

class LogicWizard(QWizard):
    """
    Guided wizard for adding I/O connections to the Logic Graph.

    Parameters
    ----------
    editor_state : EditorState
        The live editor state (things, brushes).
    graph_scene : LogicGraphScene
        The scene to add connections to.  The caller must call
        graph_scene.apply_to_entities() (or press Apply in the graph window)
        to persist the connections to the map.
    """

    def __init__(self, editor_state, graph_scene, parent=None):
        super().__init__(parent)
        self.editor_state = editor_state
        self.graph_scene  = graph_scene

        self.setWindowTitle("Logic Wizard")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(640, 540)
        self.setStyleSheet(WIZARD_STYLE)
        self.setOption(QWizard.HaveHelpButton,         False)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.FinishButton, "Add to Graph")
        self.setButtonText(QWizard.NextButton,   "Next  ›")
        self.setButtonText(QWizard.BackButton,   "‹  Back")

        self._p_scenario = ScenarioPage(self)
        self._p_entities = EntitiesPage(editor_state, self)
        self._p_options  = OptionsPage(self)
        self._p_summary  = SummaryPage(self)

        self.setPage(ScenarioPage.PAGE_ID, self._p_scenario)
        self.setPage(EntitiesPage.PAGE_ID, self._p_entities)
        self.setPage(OptionsPage.PAGE_ID,  self._p_options)
        self.setPage(SummaryPage.PAGE_ID,  self._p_summary)

        self.accepted.connect(self._apply)

    def _apply(self):
        sc = self._p_scenario.selected_scenario()
        ep = self._p_entities
        op = self._p_options
        if not sc:
            return

        delay            = op.global_delay()
        fire_once_global = op.global_fire_once()
        added            = 0

        for wire in sc["wiring"]:
            src_role, out_pin, dst_role, in_pin, _desc = wire
            src_name = ep.entity_for_role(src_role)
            dst_name = ep.entity_for_role(dst_role)
            if not src_name or not dst_name:
                continue

            fo = fire_once_global
            if "fire_once" in [p["key"] for p in sc.get("params", [])]:
                v = op.param_value("fire_once")
                if v is not None:
                    fo = bool(v)

            ok = self.graph_scene.add_connection_by_name(
                src_name, out_pin,
                dst_name, in_pin,
                param="", delay=delay, fire_once=fo,
            )
            if ok:
                added += 1

        if added:
            QMessageBox.information(
                self.parentWidget(),
                "Wizard complete",
                f"{added} connection(s) added to the graph.\n\n"
                "Press ✔ Apply in the Logic Graph Editor to save them to the map.",
            )
        else:
            QMessageBox.warning(
                self.parentWidget(),
                "Nothing added",
                "No connections could be created.\n"
                "Make sure the selected entities have the required pins available\n"
                "and that entity names are not empty.",
            )
