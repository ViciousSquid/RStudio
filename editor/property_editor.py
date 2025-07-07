from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QFormLayout, QGridLayout
from PyQt5.QtCore import Qt

class PropertyEditor(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setLabelAlignment(Qt.AlignLeft)
        self.set_object(None)

    def set_object(self, obj):
        """Populates the property editor with the properties of the given object."""
        # Clear the old layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.current_object = obj
        if obj is None:
            self.layout.addRow(QLabel("No object selected"))
            return

        # --- Display object type ---
        obj_type = type(obj).__name__ if not isinstance(obj, dict) else "Brush"
        self.layout.addRow(QLabel(f"<h3>{obj_type}</h3>"))

        # --- Handle properties based on object type ---
        if isinstance(obj, dict): # It's a brush
            self.add_vector_editor("Position", obj, 'pos')
            self.add_vector_editor("Size", obj, 'size')
            # You can add more brush-specific properties here
        else: # It's a Thing
            self.add_vector_editor("Position", obj, 'pos')
            # Iterate through the Thing's specific properties
            for key, value in obj.properties.items():
                self.add_property_editor(key.capitalize(), obj, key)
    
    def add_vector_editor(self, label_text, obj, key):
        """Adds a 3-component vector editor (e.g., for position, size)."""
        container = QWidget()
        grid_layout = QGridLayout(container)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        labels = ['X', 'Y', 'Z']
        vector = obj[key] if isinstance(obj, dict) else getattr(obj, key)

        for i in range(3):
            grid_layout.addWidget(QLabel(labels[i]), 0, i)
            editor = QLineEdit(str(vector[i]))
            
            # Use a lambda to capture the necessary variables
            update_func = lambda text, index=i: self.update_vector_property(obj, key, index, text)
            editor.textChanged.connect(update_func)
            
            grid_layout.addWidget(editor, 1, i)
            
        self.layout.addRow(label_text, container)

    def add_property_editor(self, label_text, obj, key):
        """Adds an editor for a single property."""
        value = obj.properties[key]
        editor = QLineEdit(str(value))

        update_func = lambda text: self.update_thing_property(obj, key, text)
        editor.textChanged.connect(update_func)
        
        self.layout.addRow(label_text, editor)

    def update_vector_property(self, obj, key, index, text):
        """Updates a single component of a vector property."""
        try:
            value = float(text)
            if isinstance(obj, dict):
                obj[key][index] = value
            else:
                getattr(obj, key)[index] = value
            
            # For 'Things', call their update method if it exists
            if hasattr(obj, 'update_from_properties'):
                obj.update_from_properties()

            self.editor.update_views()
        except ValueError:
            pass # Ignore non-numeric input for now

    def update_thing_property(self, obj, key, text):
        """Updates a property in a Thing's properties dictionary."""
        # Try to convert to float/int if possible, otherwise keep as string
        try:
            value = float(text)
            if value.is_integer(): value = int(value)
        except ValueError:
            value = text
            
        obj.properties[key] = value
        
        if hasattr(obj, 'update_from_properties'):
            obj.update_from_properties()
            
        self.editor.update_views()