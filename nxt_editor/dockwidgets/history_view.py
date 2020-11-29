# Builtin
import logging

# External
from Qt import QtWidgets

# Internal
import nxt_editor
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class HistoryView(DockWidgetBase):

    def __init__(self, parent=None):
        super(HistoryView, self).__init__(title='History View', parent=parent)
        self.undo_view = QtWidgets.QUndoView()
        self.setWidget(self.undo_view)

    def set_stage_model(self, model):
        super(HistoryView, self).set_stage_model(model)
        self.undo_view.setStack(model.undo_stack)
