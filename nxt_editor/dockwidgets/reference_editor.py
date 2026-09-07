"""Edit which layers a layer references.

A reference is stored as written, and that is usually partial: a name, or
a path under one of the file roots. Storing what resolved on this machine
would pin the graph to this machine, so the list here is the stored form
and the resolved form is a way of looking at it, not a way of editing it.

Nothing is written to disk. Accepting applies the change to the open
graph, which reloads the referenced layers and recomposites, and marks the
layer unsaved like any other edit. Saving the layer writes it.
"""
# Builtin
import logging
import os

# External
from Qt import QtCore, QtWidgets, QtGui

# Internal
import nxt_editor
from nxt import nxt_io

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

MISSING_COLOR = QtGui.QColor('#B14A4A')
RESOLVED_COLOR = QtGui.QColor('#9A9A9A')


class ReferenceEditor(QtWidgets.QDialog):
    """Edit the references of one open layer."""

    def __init__(self, model, layer_path=None, parent=None):
        """
        :param model: StageModel to edit
        :param layer_path: real path of the layer to start on, defaults to
            the top layer
        :type layer_path: str | None
        """
        super(ReferenceEditor, self).__init__(parent=parent)
        self.model = model
        self.setWindowTitle('Reference Editor')
        self.setModal(True)
        self.resize(720, 380)
        # The stored strings being edited. The list widget shows either
        # these or what they resolve to, and only these are ever saved.
        self.references = []
        self.showing_resolved = False

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.setLayout(layout)

        # -- which layer ------------------------------------------------
        layer_row = QtWidgets.QHBoxLayout()
        layer_row.setSpacing(6)
        layout.addLayout(layer_row)
        layer_row.addWidget(QtWidgets.QLabel('Layer'))
        self.layer_combo = QtWidgets.QComboBox()
        self.layer_combo.setToolTip('Only layers open in this graph, and not '
                                    'locked, can have their references '
                                    'edited')
        layer_row.addWidget(self.layer_combo, 1)

        self.resolved_button = QtWidgets.QPushButton('Show Resolved')
        self.resolved_button.setCheckable(True)
        self.resolved_button.setToolTip('Switch every row between the path '
                                        'as stored and the path it resolves '
                                        'to')
        self.resolved_button.toggled.connect(self.set_showing_resolved)
        layer_row.addWidget(self.resolved_button)

        # -- the references ---------------------------------------------
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(6)
        layout.addLayout(body, 1)

        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list.setAlternatingRowColors(True)
        self.list.itemChanged.connect(self.on_item_edited)
        self.list.currentRowChanged.connect(self.update_buttons)
        body.addWidget(self.list, 1)

        buttons = QtWidgets.QVBoxLayout()
        buttons.setSpacing(4)
        body.addLayout(buttons)
        self.add_button = self._button(buttons, 'Add...', self.add_reference,
                                       'Pick a layer to reference')
        self.remove_button = self._button(buttons, 'Remove',
                                          self.remove_reference,
                                          'Remove the selected reference')
        buttons.addSpacing(8)
        self.up_button = self._button(buttons, 'Move Up',
                                      lambda: self.move_reference(-1),
                                      'References are a stack; order counts')
        self.down_button = self._button(buttons, 'Move Down',
                                        lambda: self.move_reference(1),
                                        'References are a stack; order counts')
        buttons.addStretch()

        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.populate_layers(layer_path)
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)

    def _button(self, layout, text, slot, tip):
        button = QtWidgets.QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    # -- layers ---------------------------------------------------------

    def populate_layers(self, layer_path=None):
        """Fill the layer picker with the layers we may edit."""
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer in self.model.get_editable_reference_layers():
            self.layer_combo.addItem(str(layer.get_alias()), layer.real_path)
        self.layer_combo.blockSignals(False)
        index = 0
        if layer_path:
            found = self.layer_combo.findData(layer_path)
            if found >= 0:
                index = found
            else:
                logger.info('%s cannot have its references edited, showing '
                            'the top layer instead' % layer_path)
        self.layer_combo.setCurrentIndex(index)
        self.load_references()

    @property
    def layer_path(self):
        return self.layer_combo.currentData()

    def layer_dir(self):
        """The directory of the layer being edited.

        A reference written relative to its own layer resolves against
        this, which is why the preview needs it.
        """
        path = self.layer_path
        return os.path.dirname(path) if path else ''

    def on_layer_changed(self, _index):
        self.load_references()

    def load_references(self):
        self.references = self.model.get_layer_references(self.layer_path)
        self.refresh_list()

    # -- the list -------------------------------------------------------

    def set_showing_resolved(self, resolved):
        """Flip every row between the stored path and the resolved one."""
        self.showing_resolved = resolved
        self.resolved_button.setText('Show Stored' if resolved
                                     else 'Show Resolved')
        self.refresh_list()

    def refresh_list(self):
        current = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        missing = 0
        for reference in self.references:
            resolved, found = nxt_io.expand_reference_path(reference,
                                                           self.layer_dir())
            text = resolved if self.showing_resolved else reference
            item = QtWidgets.QListWidgetItem(text)
            if self.showing_resolved:
                # Resolved is a view of the stored path, not another place
                # to type. Editing it would store this machine's answer.
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                item.setForeground(RESOLVED_COLOR)
            else:
                item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            if not found:
                item.setForeground(MISSING_COLOR)
                item.setToolTip('Not found. Looked at %s' % resolved)
                missing += 1
            else:
                item.setToolTip(resolved if not self.showing_resolved
                                else reference)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if current < 0 and self.references:
            current = 0
        self.list.setCurrentRow(min(current, len(self.references) - 1))
        self.update_status(missing)
        self.update_buttons()

    def update_status(self, missing):
        if missing:
            self.status.setText(
                '%d reference%s could not be found. They are kept as written '
                'in case they resolve elsewhere.'
                % (missing, '' if missing == 1 else 's'))
            self.status.setStyleSheet('color: %s;' % MISSING_COLOR.name())
        elif self.changed():
            self.status.setText('Applying will reload the referenced layers '
                                'and recomposite.')
            self.status.setStyleSheet('color: grey;')
        else:
            self.status.setText('')

    def update_buttons(self, *_args):
        row = self.list.currentRow()
        has_row = row >= 0
        editing_stored = not self.showing_resolved
        self.remove_button.setEnabled(has_row)
        self.up_button.setEnabled(has_row and row > 0)
        self.down_button.setEnabled(has_row
                                    and row < len(self.references) - 1)
        self.add_button.setEnabled(bool(self.layer_path))
        # Reordering and removing change the stored list, which is fine in
        # either view; typing is not.
        self.list.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            if editing_stored else QtWidgets.QAbstractItemView.NoEditTriggers)

    def on_item_edited(self, item):
        if self.showing_resolved:
            return
        row = self.list.row(item)
        if 0 <= row < len(self.references):
            self.references[row] = item.text().strip()
            self.refresh_list()

    # -- editing --------------------------------------------------------

    def add_reference(self):
        start = self.layer_dir() or os.getcwd()
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Reference layer', start, 'nxt files (*.nxt *.nxtb)')
        if not path:
            return
        self.references.append(self.as_stored(path))
        self.refresh_list()
        self.list.setCurrentRow(len(self.references) - 1)

    def as_stored(self, path):
        """How a chosen file should be written into the layer.

        Relative to the layer when it sits alongside it, which is what
        keeps a graph portable. Anything else is stored whole; making a
        path relative across drives or out of a root would be worse than
        being explicit.
        """
        path = path.replace(os.path.sep, '/')
        directory = self.layer_dir()
        if not directory:
            return path
        try:
            relative = os.path.relpath(path, directory).replace(os.path.sep,
                                                                '/')
        except ValueError:
            # Different drive on Windows.
            return path
        if relative.startswith('..'):
            return path
        return relative

    def remove_reference(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.references):
            self.references.pop(row)
            self.refresh_list()

    def move_reference(self, offset):
        row = self.list.currentRow()
        target = row + offset
        if not (0 <= row < len(self.references)):
            return
        if not (0 <= target < len(self.references)):
            return
        self.references[row], self.references[target] = (
            self.references[target], self.references[row])
        self.refresh_list()
        self.list.setCurrentRow(target)

    # -- applying -------------------------------------------------------

    def changed(self):
        stored = self.model.get_layer_references(self.layer_path)
        return [r for r in self.references if r] != stored

    def accept(self):
        references = [r for r in self.references if r]
        if not self.changed():
            # Nothing to apply, so no recomposite and no unsaved marker.
            super(ReferenceEditor, self).accept()
            return
        self.model.set_layer_references(self.layer_path, references)
        super(ReferenceEditor, self).accept()
