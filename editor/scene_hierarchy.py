from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, 
                             QTreeWidgetItemIterator) # <-- Added missing import
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt

from editor.things import Thing 

class SceneHierarchy(QWidget):
    """
    A widget that displays all the objects (brushes and things) in the scene
    in a hierarchical tree view.
    """
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        
        # --- UI Setup ---
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Scene")
        layout.addWidget(self.tree)

        # --- Icon ---
        self.lock_icon = QIcon("assets/lock.png") 

        # --- Connections ---
        self.tree.itemSelectionChanged.connect(self.on_selection_changed)

    def populate(self, brushes, things):
        """
        Clears and re-populates the tree with the current brushes and things 
        from the scene.
        """
        self.tree.blockSignals(True)
        self.tree.clear()

        # --- Brushes Section ---
        brush_parent = QTreeWidgetItem(self.tree, ["Brushes"])
        for i, brush in enumerate(brushes):
            name = f"Brush {i}"
            item = QTreeWidgetItem(brush_parent, [name])
            item.setData(0, Qt.UserRole, brush) 

            if brush.get('lock', False):
                item.setIcon(0, self.lock_icon)
            else:
                item.setIcon(0, QIcon())

        # --- Things Section ---
        thing_parent = QTreeWidgetItem(self.tree, ["Things"])
        for thing in things:
            item = QTreeWidgetItem(thing_parent, [thing.name])
            item.setData(0, Qt.UserRole, thing)

        self.tree.expandAll()
        self.tree.blockSignals(False)

    def on_selection_changed(self):
        """
        Handles when the user selects an item in the tree.
        """
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        selected_item = selected_items[0]
        obj = selected_item.data(0, Qt.UserRole) 

        if obj:
            self.editor.select_object(obj)

    def select_object(self, obj_to_select):
        """
        Finds and selects the tree item corresponding to the given object.
        """
        if obj_to_select is None:
            self.tree.clearSelection()
            return
            
        iterator = QTreeWidgetItemIterator(self.tree, QTreeWidgetItemIterator.All)
        while iterator.value():
            item = iterator.value()
            item_data = item.data(0, Qt.UserRole)

            if item_data is obj_to_select:
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(item)
                self.tree.blockSignals(False)
                break
            
            iterator += 1