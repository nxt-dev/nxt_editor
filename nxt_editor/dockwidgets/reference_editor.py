"""Edit which layers a layer references.

A reference is stored as written, and that is usually partial: a name, or
a path under one of the file roots. Storing what resolved on this machine
would pin the graph to this machine, so the list here is the stored form
and the resolved form is a way of looking at it, not a way of editing it.

Nothing is written to disk. Accepting applies the change to the open
graph, which reloads the referenced layers and recomposites, and marks the
layer unsaved like any other edit. Saving the layer writes it.

On the layout: the paths are the content and they are long, so they get
the full width, and the controls are an icon strip under them rather than
a column of text buttons as tall as the list. The layer picker sizes to
its own contents with the resolved toggle pinned beside it, so the toggle
does not slide about as one layer name replaces another.
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

# From the application palette, so this dialog belongs to nxt rather than
# resembling it: #787878 is the secondary text, #B14A4A the warning red.
MISSING_COLOR = QtGui.QColor('#B14A4A')
RESOLVED_COLOR = QtGui.QColor('#787878')

# The stored path lives on the item, because what the item says is the
# resolved path half the time and the two must not be confused.
STORED_ROLE = QtCore.Qt.UserRole + 1


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
        self.resize(480, 300)
        self.setMinimumSize(380, 220)
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
        layer_row.setSpacing(4)
        layout.addLayout(layer_row)
        layer_row.addWidget(QtWidgets.QLabel('Layer'))
        self.layer_combo = QtWidgets.QComboBox()
        # Sized to its contents, with the stretch after the toggle, so the
        # toggle keeps its place instead of tracking the layer name.
        self.layer_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToContents)
        self.layer_combo.setToolTip('Only layers open in this graph, and not '
                                    'locked, can have their references '
                                    'edited')
        layer_row.addWidget(self.layer_combo)

        self.resolved_button = self._tool_button(
            'Show where each reference resolves to on this machine',
            icon=':icons/icons/resolved_12.png', text=u'∷')
        self.resolved_button.setCheckable(True)
        self.resolved_button.toggled.connect(self.set_showing_resolved)
        layer_row.addWidget(self.resolved_button)
        layer_row.addStretch()

        # -- the references ---------------------------------------------
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list.setAlternatingRowColors(True)
        # References are a stack, so dragging one is a real edit and the
        # most direct way to say what the order should be.
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.list.itemChanged.connect(self.on_item_edited)
        self.list.currentRowChanged.connect(self.update_buttons)
        self.list.model().rowsMoved.connect(self.on_rows_moved)
        layout.addWidget(self.list, 1)

        # -- adding -----------------------------------------------------
        # Typed, because most references are partial and a file dialog can
        # only offer files that exist here. There was no way to write
        # $SHOW/lib/rig.nxt at all without adding something real and then
        # editing it.
        add_row = QtWidgets.QHBoxLayout()
        add_row.setSpacing(4)
        layout.addLayout(add_row)
        self.add_edit = QtWidgets.QLineEdit()
        self.add_edit.setPlaceholderText('Type or paste a path, partial paths '
                                         'welcome, then Enter')
        self.add_edit.setToolTip('Stored exactly as you write it, so a path '
                                 'under a file root keeps resolving on other '
                                 'machines')
        self.add_edit.returnPressed.connect(self.add_typed_reference)
        self.add_edit.textChanged.connect(self.update_buttons)
        add_row.addWidget(self.add_edit, 1)
        # No folder icon in the application's set, and the ellipsis is the
        # conventional way to say a picker opens here anyway.
        self.browse_button = self._tool_button('Pick a layer file',
                                               text=u'…')
        self.browse_button.clicked.connect(self.add_reference)
        add_row.addWidget(self.browse_button)

        # -- the controls -----------------------------------------------
        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(2)
        layout.addLayout(controls)
        self.add_button = self._tool_button('Add the path written above',
                                            icon=':icons/icons/plus.png',
                                            text='+')
        self.add_button.clicked.connect(self.add_typed_reference)
        controls.addWidget(self.add_button)
        self.remove_button = self._tool_button('Remove the selected reference',
                                               icon=':icons/icons/minus.png',
                                               text=u'−')
        self.remove_button.clicked.connect(self.remove_reference)
        controls.addWidget(self.remove_button)
        controls.addSpacing(8)
        self.up_button = self._tool_button('Move up. References are a stack, '
                                           'so the order counts',
                                           text=u'▲')
        self.up_button.clicked.connect(lambda: self.move_reference(-1))
        controls.addWidget(self.up_button)
        self.down_button = self._tool_button('Move down. References are a '
                                             'stack, so the order counts',
                                             text=u'▼')
        self.down_button.clicked.connect(lambda: self.move_reference(1))
        controls.addWidget(self.down_button)
        controls.addStretch()

        # One line, and hidden when it has nothing to say, so the dialog
        # does not hold space open for silence.
        self.status = QtWidgets.QLabel('')
        self.status.setVisible(False)
        controls.addWidget(self.status)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        # Enter in the path field adds the path. Left alone it would reach
        # the default button and apply the dialog instead, throwing away
        # what was just typed.
        for button in self.button_box.buttons():
            button.setAutoDefault(False)
            button.setDefault(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.populate_layers(layer_path)
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)

    def _tool_button(self, tip, icon=None, text=''):
        """A small square button in the application's own style.

        QToolButton is what the stylesheet already dresses, hover and
        checked states included, so these look like the rest of nxt
        without this dialog restating any of it.
        """
        button = QtWidgets.QToolButton()
        button.setToolTip(tip)
        button.setAutoRaise(True)
        if icon:
            pixmap = QtGui.QPixmap(icon)
            if not pixmap.isNull():
                button.setIcon(QtGui.QIcon(pixmap))
                return button
        # No such resource, so say it in text rather than show a blank.
        button.setText(text)
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
        self.resolved_button.setToolTip(
            'Showing where each reference resolves to. Click to show them as '
            'stored' if resolved else
            'Show where each reference resolves to on this machine')
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
            # What it says changes with the toggle; what it is does not.
            item.setData(STORED_ROLE, reference)
            flags = item.flags() | QtCore.Qt.ItemIsDragEnabled
            if self.showing_resolved:
                # Resolved is a view of the stored path, not another place
                # to type. Editing it would store this machine's answer.
                flags &= ~QtCore.Qt.ItemIsEditable
                item.setForeground(RESOLVED_COLOR)
            else:
                flags |= QtCore.Qt.ItemIsEditable
            item.setFlags(flags)
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
                '%d could not be found' % missing
                if missing > 1 else '1 could not be found')
            self.status.setToolTip(
                'Kept as written, in case they resolve on another machine.')
            self.status.setStyleSheet('color: %s;' % MISSING_COLOR.name())
            self.status.setVisible(True)
        elif self.changed():
            self.status.setText('Will reload and recomposite')
            self.status.setToolTip('Applying reloads the referenced layers '
                                   'and recomposites the graph.')
            self.status.setStyleSheet('color: %s;' % RESOLVED_COLOR.name())
            self.status.setVisible(True)
        else:
            self.status.setText('')
            self.status.setVisible(False)

    def update_buttons(self, *_args):
        row = self.list.currentRow()
        has_row = row >= 0
        editing_stored = not self.showing_resolved
        self.remove_button.setEnabled(has_row)
        self.up_button.setEnabled(has_row and row > 0)
        self.down_button.setEnabled(has_row
                                    and row < len(self.references) - 1)
        has_text = bool(self.add_edit.text().strip())
        self.add_button.setEnabled(bool(self.layer_path) and has_text)
        self.browse_button.setEnabled(bool(self.layer_path))
        self.add_edit.setEnabled(bool(self.layer_path))
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

    def on_rows_moved(self, *_args):
        """Take the new order from the rows after a drag.

        Read back the stored path, never the text: half the time the text
        is where the reference resolved to on this machine, and storing
        that would pin the graph here.
        """
        moved = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            stored = item.data(STORED_ROLE)
            moved.append(stored if stored is not None else item.text())
        if moved != self.references:
            self.references = moved
            self.refresh_list()

    # -- editing --------------------------------------------------------

    def add_typed_reference(self):
        """Add whatever is written in the path field, exactly as written.

        Not put through as_stored: a typed path is already the form the
        person means it to be kept in. Rewriting $SHOW/lib/rig.nxt into
        something relative to this layer, or into where it happens to land
        on this machine, would undo the reason for typing it.
        """
        reference = self.add_edit.text().strip()
        if not reference:
            return
        self.references.append(reference)
        self.add_edit.clear()
        self.refresh_list()
        self.list.setCurrentRow(len(self.references) - 1)

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
