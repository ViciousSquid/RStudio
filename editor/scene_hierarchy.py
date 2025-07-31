from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator
from PyQt5.QtCore import Qt
from editor.things import Thing

class SceneHierarchy(QTreeWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setHeaderLabel("Scene")
        self.itemSelectionChanged.connect(self.on_selection_changed)

    def update_list(self, brushes, things):
        """
        Clears and repopulates the tree with the current scene objects.
        """
        self.clear()
        
        # Add brushes to the hierarchy
        if brushes:
            brush_root = QTreeWidgetItem(self, ["Brushes"])
            for i, brush in enumerate(brushes):
                item = QTreeWidgetItem(brush_root, [f"Brush {i}"])
                item.setData(0, Qt.UserRole, brush) # Attach the brush object
        
        # Add things to the hierarchy
        if things:
            thing_root = QTreeWidgetItem(self, ["Things"])
            for thing in things:
                # Assuming things have a 'name' or similar attribute
                name = getattr(thing, 'name', 'Thing') 
                item = QTreeWidgetItem(thing_root, [name])
                item.setData(0, Qt.UserRole, thing) # Attach the thing object

        self.expandAll()

    def on_selection_changed(self):
        """
        When an item is clicked in the hierarchy, select it in the editor.
        """
        selected_items = self.selectedItems()
        if selected_items:
            item_data = selected_items[0].data(0, Qt.UserRole)
            # Prevent recursive loop by checking if it's already selected
            if self.editor.selected_object is not item_data:
                self.editor.select_object(item_data)
        elif self.editor.selected_object is not None:
            self.editor.select_object(None)

    def select_item_by_data(self, data_to_select):
        """
        Finds and selects the tree item corresponding to the given data object.
        If data_to_select is None, it clears the selection.
        """
        if data_to_select is None:
            self.clearSelection()
            return

        # Iterate through all items in the tree to find a match
        iterator = QTreeWidgetItemIterator(self)
        while iterator.value():
            item = iterator.value()
            item_data = item.data(0, Qt.UserRole)
            if item_data is data_to_select:
                self.setCurrentItem(item) # Select the found item
                return
            iterator += 1