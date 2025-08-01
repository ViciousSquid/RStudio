from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt5.QtGui import QIcon

class SceneHierarchy(QTreeWidget):
    """
    Manages the tree view list of all objects in the scene.
    When an item is selected in this list, it notifies the main window
    to trigger a full application UI refresh.
    """

    def __init__(self, main_window):
        """
        Initializes the scene hierarchy widget.
        """
        super().__init__()
        self.main_window = main_window
        self.setHeaderLabel("Scene Objects")

        # Create the lock icon once and reuse it
        self.lock_icon = QIcon("assets/lock.png")
        self.itemSelectionChanged.connect(self.handle_selection_change)

    def handle_selection_change(self):
        """
        This method is called automatically whenever the selection changes.
        It finds the selected object and tells the main window.
        """
        selected_items = self.selectedItems()
        if not selected_items:
            return
        first_item = selected_items[0]
        selected_object = self.get_object_from_item(first_item)

        if selected_object is not None:
            self.main_window.set_selected_object(selected_object)

    def get_object_from_item(self, item: QTreeWidgetItem):
        """
        Retrieves an application object (brush or thing) from a QTreeWidget item.
        """
        if not item:
            return None
        try:
            object_name = item.data(0, Qt.UserRole)
            if object_name is None:
                return None
            # Search through both lists to find the matching object
            for obj in self.main_window.brushes + self.main_window.things:
                if isinstance(obj, dict) and obj.get('name') == object_name:
                    return obj
                elif hasattr(obj, 'name') and obj.name == object_name:
                    return obj
        except Exception as e:
            print(f"Error retrieving object from item: {e}")

        return None

    def refresh_list(self, all_brushes, all_things, selected_item):
        """
        Clears and repopulates the list with brushes and things,
        assigning unique names and a lock icon where appropriate.
        """
        self.blockSignals(True)
        self.clear()

        brush_counter = 1

        brush_parent = QTreeWidgetItem(self, ["Brushes"])
        for brush_dict in all_brushes:
            display_name = brush_dict.get('name')
            if not display_name:
                display_name = f"Brush {brush_counter}"
                brush_dict['name'] = display_name

            brush_counter += 1
            item = QTreeWidgetItem(brush_parent, [display_name])
            item.setData(0, Qt.UserRole, display_name)

            # Check for lock status and apply icon
            if brush_dict.get('lock', False):
                item.setIcon(0, self.lock_icon)

            if selected_item is brush_dict:
                self.setCurrentItem(item)

        thing_parent = QTreeWidgetItem(self, ["Things"])
        for thing in all_things:
            display_name = getattr(thing, 'name', 'Unnamed Thing')

            item = QTreeWidgetItem(thing_parent, [display_name])
            item.setData(0, Qt.UserRole, display_name)
            if selected_item is thing:
                self.setCurrentItem(item)

        self.expandAll()
        self.blockSignals(False)
