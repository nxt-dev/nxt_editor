# Built-in
import re
import logging

# External
from Qt import QtCore
from Qt.QtWidgets import QDockWidget

# Internal
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class DockWidgetBase(QDockWidget):

    """All of nxt's dock widgets have a lot in common, this thin class
    mutates QDockWidget to nxt preferences"""

    def __init__(self, title, parent=None, graph_model=None,
                 minimum_width=None, minimum_height=None):
        # We have to prefix the object name with Nxt so we don't blow up our
        # host context.
        safe_name = 'Nxt ' + title
        super(DockWidgetBase, self).__init__(safe_name, parent=parent)
        self.setFeatures(QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable |
                         QDockWidget.DockWidgetFloatable)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        # set minimum dimensions
        if minimum_width:
            self.setMinimumWidth(minimum_width)

        if minimum_height:
            self.setMinimumHeight(minimum_height)

        # set title
        self.title = title
        self.setWindowTitle(title)
        # keep only a-zA-Z0-9 for object name
        self.setObjectName(re.sub(r'[^a-zA-Z0-9]', '', safe_name))

        # set title size
        self.setStyleSheet('''QDockWidget{
                                font-size: 7pt;
                                font-weight: bold;
                                color: grey;
                              }

                              QDockWidget::title{
                                text-align: center;
                                color: grey;
                              }
                              ''')

        # set graph model
        self.stage_model = graph_model
        self.model_signal_connections = []
        self.topLevelChanged.connect(self.on_window_status_changed)

    def set_stage_model(self, stage_model):
        """Sets the stage model for docwidgets to use, also calls the
        connection handling method.
        :param stage_model: StageModel
        """
        if self.stage_model:
            self.set_stage_model_connections(self.stage_model, False)
        self.stage_model = stage_model
        if self.stage_model:
            self.set_stage_model_connections(self.stage_model, True)

    def on_window_status_changed(self, is_window):
        if is_window:
            flags = (
                QtCore.Qt.Window |
                QtCore.Qt.CustomizeWindowHint |
                QtCore.Qt.WindowMinMaxButtonsHint |
                QtCore.Qt.WindowCloseButtonHint
            )
            self.setWindowFlags(flags)
            self.show()

    def set_stage_model_connections(self, model, connect):
        """Connect and disconnect signals from the docwidget.
        Called by `set_graph_model`.
        Sub-classes can add their own custom connection mapping before
        supering this method. Example:
            self.model_signal_connections = [
                (model.a_signal, self.method_to_be_called),
                (model.node_changed, self.update_title)
            ]
            super(SomeDoc, self).set_stage_model_connection(model, connect)
        :param model: Model to change connection status to.
        :type model: StageModel
        :param connect: True if connecting, False if disconnecting
        :type connect: bool
        """
        self.model_signal_connections += [
            (model.destroyed, self.on_stage_model_destroyed)
        ]
        for model_signal, my_func in self.model_signal_connections:
            if connect:
                model_signal.connect(my_func)
            else:
                model_signal.disconnect(my_func)
        self.model_signal_connections = []

    def on_stage_model_destroyed(self):
        """Called when the model's `destroyed` signal is emitted. Should be
        overloaded on sub-classes as its a good place to hide yo kids so users
        can't accidentally get to them after the model is destroyed.
        """
        self.stage_model = None
