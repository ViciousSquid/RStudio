from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu
from PyQt5.QtGui import QIcon, QColor, QBrush, QFont # Import QFont
from PyQt5.QtCore import Qt

class SceneHierarchy(QTreeWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        # Remove the header by setting its height to 0
        self.header().setVisible(False) 

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_menu)
        self.lock_icon = QIcon("assets/lock.png")
        self.hidden_icon = QIcon("assets/hidden.png")
        self.itemSelectionChanged.connect(self.handle_selection_change)

    def refresh_list(self):
        self.blockSignals(True)
        self.clear()
        
        # Define font for headers
        header_font = QFont()
        header_font.setBold(True)

        # Add Brushes Header
        brushes_header = QTreeWidgetItem(self, ["Brushes"])
        brushes_header.setFlags(brushes_header.flags() & ~Qt.ItemIsSelectable)
        brushes_header.setForeground(0, QBrush(QColor("white"))) # Set text color to white
        brushes_header.setFont(0, header_font) # Set font to bold
        brushes_header.setExpanded(True)
        
        # Add Brushes
        for i, brush_dict in enumerate(self.main_window.brushes):
            item_text = brush_dict.get('name', f'Brush {i+1}')
            item = QTreeWidgetItem(brushes_header, [item_text])
            item.setData(0, Qt.UserRole, ('brush', i))
            
            # Check for lock status and apply icon
            if brush_dict.get('lock', False):
                item.setIcon(0, self.lock_icon)
            if brush_dict.get('hidden', False):
                item.setIcon(0, self.hidden_icon)
            
            if self.main_window.selected_object is brush_dict:
                item.setSelected(True)

        # Add Things Header
        things_header = QTreeWidgetItem(self, ["Things"])
        things_header.setFlags(things_header.flags() & ~Qt.ItemIsSelectable)
        things_header.setForeground(0, QBrush(QColor("white"))) # Set text color to white
        things_header.setFont(0, header_font) # Set font to bold
        things_header.setExpanded(True)
        
        # Add Things
        for i, thing_obj in enumerate(self.main_window.things):
            item_text = thing_obj.name if thing_obj.name else f'Thing {i+1}'
            item = QTreeWidgetItem(things_header, [item_text])
            item.setData(0, Qt.UserRole, ('thing', i))

            if self.main_window.selected_object is thing_obj:
                item.setSelected(True)
                
        self.blockSignals(False)

    def handle_selection_change(self):
        selected_items = self.selectedItems()
        if not selected_items:
            # This can happen if the selection is cleared programmatically
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        
        if data:
            obj_type, obj_index = data
            if obj_type == 'brush':
                self.main_window.set_selected_object(self.main_window.brushes[obj_index])
            elif obj_type == 'thing':
                self.main_window.set_selected_object(self.main_window.things[obj_index])
        else:
             self.main_window.set_selected_object(None)

    def open_menu(self, position):
        menu = QMenu()
        selected_items = self.selectedItems()

        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if data and data[0] == 'brush':
            brush_dict = self.main_window.brushes[data[1]]
            
            # Lock/Unlock Action
            is_locked = brush_dict.get('lock', False)
            lock_action_text = "Unlock" if is_locked else "Lock"
            lock_action = menu.addAction(lock_action_text)
            
            # Hide/Show Action
            is_hidden = brush_dict.get('hidden', False)
            hide_action_text = "Show" if is_hidden else "Hide"
            hide_action = menu.addAction(hide_action_text)
            
            action = menu.exec_(self.viewport().mapToGlobal(position))

            if action == lock_action:
                self.main_window.save_state()
                brush_dict['lock'] = not is_locked
                self.main_window.update_all_ui()
            elif action == hide_action:
                self.main_window.save_state()
                brush_dict['hidden'] = not is_hidden
                self.main_window.update_all_ui()